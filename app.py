from flask import Flask, request, jsonify
import httpx
import os
from datetime import datetime, timedelta
import re

app = Flask(__name__)

# Header image URL
HEADER_URL = 'https://mghunch.github.io/hunch-assets/Header_ToDo.png'

# Airtable config
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = 'app8CI7NAZqhQ4G1Y'
AIRTABLE_PROJECTS_TABLE = 'Projects'

# Stage icons mapping
STAGE_ICONS = {
    'Clarify': '💬',
    'Craft': '✏️',
    'Refine': '🔄',
    'Deliver': '📦',
    'Simplify': '🧠'
}


def format_time(time_str):
    """Format time to '3.00 pm' format"""
    if not time_str:
        return ''
    try:
        # Handle various input formats
        for fmt in ['%H:%M:%S', '%H:%M', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S']:
            try:
                if 'T' in time_str:
                    time_obj = datetime.strptime(time_str[:19], fmt)
                else:
                    time_obj = datetime.strptime(time_str, fmt)
                return time_obj.strftime('%-I.%M %p').lower()
            except ValueError:
                continue
        return time_str
    except:
        return time_str


def format_duration(minutes):
    """Format duration to '30 mins' or '1 hr' or '1.5 hrs'"""
    if not minutes:
        return ''
    try:
        mins = int(minutes)
        if mins < 60:
            return f"{mins} mins"
        elif mins == 60:
            return "1 hr"
        elif mins % 60 == 0:
            return f"{mins // 60} hrs"
        else:
            hours = mins / 60
            return f"{hours:.1g} hrs"
    except:
        return ''


def format_date_short(date_str):
    """Format date to 'Mon 7 Jan' format"""
    if not date_str:
        return ''
    try:
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']:
            try:
                date_obj = datetime.strptime(date_str[:10], fmt)
                return date_obj.strftime('%a %-d %b')
            except ValueError:
                continue
        return date_str
    except:
        return date_str


def clean_meeting_title(title):
    """Clean up meeting title - remove FW:, RE:, etc."""
    if not title:
        return ''
    # Remove common prefixes
    title = re.sub(r'^(FW:|RE:|Fwd:|Re:)\s*', '', title, flags=re.IGNORECASE)
    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + '...'
    return title.strip()


def extract_location(meeting):
    """Extract location from meeting - client name, Teams, or physical location"""
    location = meeting.get('location', '')
    is_teams = meeting.get('isTeams', False) or 'teams' in location.lower()
    
    # Check if Teams meeting
    if is_teams or 'teams.microsoft.com' in location.lower():
        return 'Teams'
    
    # Check for client in attendees or title
    attendees = meeting.get('attendees', [])
    title = meeting.get('subject', '')
    
    # Client domain mapping
    client_domains = {
        'one.nz': 'One NZ',
        'sky.co.nz': 'Sky',
        'tower.co.nz': 'Tower',
        'fisherfunds.co.nz': 'Fisher Funds',
        'firestop.co.nz': 'Firestop'
    }
    
    for attendee in attendees:
        email = attendee.get('email', '').lower()
        for domain, client_name in client_domains.items():
            if domain in email:
                return client_name
    
    # If physical location provided
    if location and location.lower() not in ['teams', 'microsoft teams', '']:
        # Shorten if too long
        if len(location) > 20:
            return location[:17] + '...'
        return location
    
    return 'Teams'  # Default


def filter_meetings(meetings):
    """Filter out Focus time, Admin time, and other exclusions"""
    excluded_keywords = ['focus time', 'admin time', 'blocked', 'busy']
    
    filtered = []
    for meeting in meetings:
        title = meeting.get('subject', '').lower()
        # Skip if title contains excluded keywords
        if any(keyword in title for keyword in excluded_keywords):
            continue
        filtered.append(meeting)
    
    return filtered


def get_stage_icon(stage):
    """Get icon for stage"""
    if not stage:
        return '📋'
    return STAGE_ICONS.get(stage.capitalize(), '📋')


def get_working_days_from_now(days):
    """Get date that is N working days from now (skipping weekends)"""
    current = datetime.now().date()
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday = 0, Friday = 4
            added += 1
    return current


def get_jobs_from_airtable():
    """Fetch all in-progress jobs from Airtable and sort by due date"""
    if not AIRTABLE_API_KEY:
        print("No Airtable API key configured")
        return [], [], []
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # Get all In Progress jobs
        filter_formula = "{Status}='In Progress'"
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_PROJECTS_TABLE}"
        params = {'filterByFormula': filter_formula}
        
        response = httpx.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        end_of_week = get_working_days_from_now(4)
        
        jobs_today = []
        jobs_this_week = []
        other_projects = []
        
        for record in records:
            fields = record.get('fields', {})
            
            # Get update due date
            update_due_str = fields.get('Update due', '')
            if isinstance(update_due_str, list):
                update_due_str = update_due_str[0] if update_due_str else ''
            
            # Parse date
            update_due = None
            if update_due_str:
                try:
                    update_due = datetime.strptime(update_due_str[:10], '%Y-%m-%d').date()
                except:
                    pass
            
            # Get update summary
            update_summary = fields.get('Update', '')
            if isinstance(update_summary, list):
                update_summary = update_summary[0] if update_summary else ''
            
            job = {
                'jobNumber': fields.get('Job Number', ''),
                'jobName': fields.get('Project Name', ''),
                'update': update_summary or 'No updates yet',
                'updateDue': update_due_str,
                'stage': fields.get('Stage', ''),
                'channelUrl': fields.get('Teams Channel URL', '#')
            }
            
            # Sort into buckets
            if update_due:
                if update_due <= tomorrow:
                    jobs_today.append(job)
                elif update_due <= end_of_week:
                    jobs_this_week.append(job)
                else:
                    other_projects.append(job)
            else:
                other_projects.append(job)
        
        # Sort each list by due date
        jobs_today.sort(key=lambda x: x.get('updateDue', ''))
        jobs_this_week.sort(key=lambda x: x.get('updateDue', ''))
        other_projects.sort(key=lambda x: x.get('updateDue', ''))
        
        return jobs_today, jobs_this_week, other_projects
        
    except Exception as e:
        print(f"Airtable error: {e}")
        return [], [], []


def build_meetings_html(meetings):
    """Build HTML for meetings section"""
    if not meetings:
        return ''
    
    rows = ''
    for meeting in meetings:
        time = format_time(meeting.get('startTime', ''))
        location = extract_location(meeting)
        title = clean_meeting_title(meeting.get('subject', ''))
        duration = format_duration(meeting.get('duration', ''))
        
        # Format: time - title - location (duration)
        duration_str = f" ({duration})" if duration else ""
        
        rows += f'''
          <tr>
            <td style="padding: 4px 0; color: #333;">{time} – {title} – {location}{duration_str}</td>
          </tr>'''
    
    return f'''
    <tr>
      <td style="padding: 10px 20px 0 20px;">
        <div style="background-color: #ED1C24; color: #ffffff; padding: 8px 15px; font-size: 14px; font-weight: bold; border-radius: 3px;">
          MEETINGS TODAY
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding: 15px 20px; border-bottom: 1px solid #eee;">
        <table cellpadding="0" cellspacing="0" style="width: 100%; font-size: 14px; color: #333;">
          {rows}
        </table>
      </td>
    </tr>'''


def build_job_html(job):
    """Build HTML for a single job"""
    job_number = job.get('jobNumber', '')
    job_name = job.get('jobName', '')
    update = job.get('update', 'No updates yet')
    due_date = format_date_short(job.get('updateDue', ''))
    stage = job.get('stage', '')
    stage_icon = get_stage_icon(stage)
    channel_url = job.get('channelUrl', '#')
    
    return f'''
    <tr>
      <td style="padding: 15px 20px; border-bottom: 1px solid #eee;">
        <p style="margin: 0 0 5px 0; font-size: 16px; font-weight: bold; color: #333;">
          {job_number} — {job_name}
        </p>
        <p style="margin: 0 0 8px 0; font-size: 14px; color: #666; line-height: 1.4;">
          {update}
        </p>
        <p style="margin: 0; font-size: 13px; color: #999;">
          🕦 {due_date} · {stage_icon} {stage} · <a href="{channel_url}" style="color: #999; text-decoration: none;">🔗 Channel</a>
        </p>
      </td>
    </tr>'''


def build_section_html(title, jobs, color="#ED1C24"):
    """Build HTML section with header and jobs"""
    if not jobs:
        return ''
    
    section = f'''
    <tr>
      <td style="padding: 20px 20px 0 20px;">
        <div style="background-color: {color}; color: #ffffff; padding: 8px 15px; font-size: 14px; font-weight: bold; border-radius: 3px;">
          {title}
        </div>
      </td>
    </tr>'''
    
    for job in jobs:
        section += build_job_html(job)
    
    return section


def build_other_projects_html(projects):
    """Build compact bullet list for other projects"""
    if not projects:
        return ''
    
    items = ''
    for p in projects:
        job_number = p.get('jobNumber', '')
        job_name = p.get('jobName', '')
        items += f'<li><strong style="color: #333;">{job_number}</strong> — {job_name}</li>'
    
    return f'''
    <tr>
      <td style="padding: 20px 20px 0 20px;">
        <div style="background-color: #666666; color: #ffffff; padding: 8px 15px; font-size: 14px; font-weight: bold; border-radius: 3px;">
          OTHER PROJECTS
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding: 15px 20px;">
        <ul style="margin: 0; padding-left: 20px; color: #666; font-size: 14px; line-height: 1.8;">
          {items}
        </ul>
      </td>
    </tr>'''


def build_todo_email(meetings, jobs_today, jobs_this_week, other_projects):
    """Build complete To Do email HTML"""
    today = datetime.now().strftime('%A, %-d %B %Y')
    
    # Filter meetings
    filtered_meetings = filter_meetings(meetings)
    
    html = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <style>
    @media screen and (max-width: 600px) {{
      .wrapper {{
        width: 100% !important;
        padding: 12px !important;
      }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 20px; font-family: Calibri, Arial, sans-serif; background-color: #f5f5f5; width: 100% !important;">
  
  <table class="wrapper" width="600" cellpadding="0" cellspacing="0" style="width: 600px; max-width: 100%; margin: 0 auto; background-color: #ffffff;">
    
    <!-- Header -->
    <tr>
      <td style="border-bottom: 4px solid #ED1C24; padding: 0;">
        <img src="{HEADER_URL}" width="600" style="width: 100%; max-width: 600px; height: auto; display: block;" alt="To Do Header">
      </td>
    </tr>
    
    <!-- Date -->
    <tr>
      <td style="padding: 20px 20px 10px 20px;">
        <p style="margin: 0; font-size: 12px; color: #999;">{today}</p>
      </td>
    </tr>
    
    {build_meetings_html(filtered_meetings)}
    {build_section_html("WORK TODAY", jobs_today, "#ED1C24")}
    {build_section_html("WORK THIS WEEK", jobs_this_week, "#666666")}
    {build_other_projects_html(other_projects)}
    
    <!-- Footer -->
    <tr>
      <td style="padding: 25px 20px; border-top: 1px solid #eee; text-align: center;">
        <p style="margin: 0 0 5px 0; font-size: 12px; color: #333; font-weight: bold;">Agency Intuition x Artificial Intelligence = AI²</p>
        <p style="margin: 0; font-size: 12px; color: #999;">Got questions? Get in touch</p>
      </td>
    </tr>
    
  </table>
  
</body>
</html>'''
    
    return html


# ===================
# TO DO ENDPOINT
# ===================
@app.route('/todo', methods=['POST'])
def todo():
    """Generate To Do email HTML"""
    try:
        data = request.get_json() or {}
        
        # Get meetings from request (sent by Power Automate)
        meetings = data.get('meetings', [])
        
        # Get jobs from Airtable
        jobs_today, jobs_this_week, other_projects = get_jobs_from_airtable()
        
        # Build HTML
        html = build_todo_email(meetings, jobs_today, jobs_this_week, other_projects)
        
        return jsonify({
            'html': html,
            'meetingsCount': len(filter_meetings(meetings)),
            'jobsTodayCount': len(jobs_today),
            'jobsThisWeekCount': len(jobs_this_week),
            'otherProjectsCount': len(other_projects)
        })
        
    except Exception as e:
        return jsonify({
            'error': 'Internal server error',
            'details': str(e)
        }), 500


# ===================
# HEALTH CHECK
# ===================
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Dot To Do',
        'endpoints': ['/todo', '/health']
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
