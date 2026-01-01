from flask import Flask, request, jsonify
from anthropic import Anthropic
import httpx
import json
import os
from datetime import datetime

app = Flask(__name__)

# Config
HEADER_URL = 'https://mghunch.github.io/hunch-assets/Header_ToDo.png'

# Anthropic client
client = Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

# Airtable config
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = 'app8CI7NAZqhQ4G1Y'
AIRTABLE_PROJECTS_TABLE = 'Projects'
AIRTABLE_UPDATES_TABLE = 'Updates'


def get_last_update_dates():
    """Fetch last update date for each job from Updates table"""
    if not AIRTABLE_API_KEY:
        return {}
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_UPDATES_TABLE}"
        params = {
            'fields[]': ['Job Number', 'Created time'],
            'sort[0][field]': 'Created time',
            'sort[0][direction]': 'desc'
        }
        
        response = httpx.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        # Build dict of job_number -> most recent update date
        last_updates = {}
        for record in records:
            fields = record.get('fields', {})
            job_number = fields.get('Job Number', '')
            created = fields.get('Created time', '')
            
            # Only keep the first (most recent) for each job
            if job_number and job_number not in last_updates:
                last_updates[job_number] = created
        
        return last_updates
        
    except Exception as e:
        print(f"Updates table error: {e}")
        return {}


def is_stale(job_number, last_updates, days=10):
    """Check if a job hasn't been updated in X days"""
    last_update = last_updates.get(job_number, '')
    if not last_update:
        return True  # No updates = stale
    
    try:
        last_date = datetime.strptime(last_update[:10], '%Y-%m-%d')
        days_since = (datetime.now() - last_date).days
        return days_since >= days
    except:
        return False

# Load prompt
with open('prompt.txt', 'r') as f:
    TODO_PROMPT = f.read()

# Stage icons mapping
STAGE_ICONS = {
    'Clarify': '💬',
    'Craft': '✏️',
    'Refine': '🔄',
    'Deliver': '📦',
    'Simplify': '🧠'
}


def strip_markdown_json(content):
    """Strip markdown code blocks from Claude's JSON response"""
    content = content.strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[1] if '\n' in content else content[3:]
    if content.endswith('```'):
        content = content.rsplit('```', 1)[0]
    return content.strip()


def get_jobs_from_airtable():
    """Fetch all in-progress jobs from Airtable"""
    if not AIRTABLE_API_KEY:
        print("No Airtable API key configured")
        return []
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # Get last update dates for stale check
        last_updates = get_last_update_dates()
        
        filter_formula = "{Status}='In Progress'"
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_PROJECTS_TABLE}"
        params = {'filterByFormula': filter_formula}
        
        response = httpx.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        jobs = []
        for record in records:
            fields = record.get('fields', {})
            
            update_due = fields.get('Update due friendly', '')
            if isinstance(update_due, list):
                update_due = update_due[0] if update_due else ''
            
            update_summary = fields.get('Update Summary', '')
            if isinstance(update_summary, list):
                update_summary = update_summary[0] if update_summary else ''
            
            job_number = fields.get('Job Number', '')
            
            # Skip jobs ending in 000, 999, 998 (retainers/special jobs)
            if job_number and (job_number.endswith('000') or job_number.endswith('999') or job_number.endswith('998')):
                continue
            
            # Check if stale (no update in 10 days)
            stale = is_stale(job_number, last_updates)
            
            jobs.append({
                'jobNumber': job_number,
                'jobName': fields.get('Project Name', ''),
                'update': update_summary or 'No updates yet',
                'updateDue': update_due,
                'stage': fields.get('Stage', ''),
                'channelUrl': fields.get('Channel Url', ''),
                'withClient': fields.get('With Client?', False),
                'stale': stale
            })
        
        return jobs
        
    except Exception as e:
        print(f"Airtable error: {e}")
        return []


def call_claude(meetings, jobs):
    """Call Claude to process meetings and prioritise work"""
    try:
        today = datetime.now().strftime('%A, %-d %B %Y')
        
        user_message = f"""Today is {today}.

Here is my calendar data from Outlook:
{json.dumps(meetings, indent=2)}

Here are my current jobs from Airtable:
{json.dumps(jobs, indent=2)}

Please process this and return the JSON as specified in your instructions."""

        response = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=4000,
            temperature=0.2,
            system=TODO_PROMPT,
            messages=[
                {'role': 'user', 'content': user_message}
            ]
        )
        
        content = response.content[0].text
        content = strip_markdown_json(content)
        return json.loads(content)
        
    except Exception as e:
        print(f"Claude error: {e}")
        return None


def get_stage_icon(stage):
    """Get icon for stage"""
    if not stage:
        return '📋'
    return STAGE_ICONS.get(stage.capitalize(), '📋')


def format_date_short(date_str):
    """Format date to 'Mon 7 Jan' format"""
    if not date_str:
        return ''
    try:
        date_obj = datetime.strptime(date_str[:10], '%Y-%m-%d')
        return date_obj.strftime('%a %-d %b')
    except:
        return date_str


def build_summary_html(fun_fact):
    """Build HTML for fun fact"""
    if not fun_fact:
        return ''
    
    return f'''
    <tr>
      <td style="padding: 10px 20px 15px 20px;">
        <p style="margin: 0; font-size: 14px; color: #333; line-height: 1.5;">
          <strong>#FOTD:</strong> <span style="font-style: italic;">{fun_fact}</span>
        </p>
      </td>
    </tr>'''


def build_meetings_html(meetings):
    """Build HTML for meetings section"""
    if not meetings:
        return ''
    
    rows = ''
    for meeting in meetings:
        time = meeting.get('time', '')
        title = meeting.get('title', '')
        location = meeting.get('location', '')
        duration = meeting.get('duration', '')
        
        duration_str = f" ({duration})" if duration else ""
        
        rows += f'''
          <tr>
            <td style="padding: 4px 0; color: #333; font-weight: bold; white-space: nowrap; vertical-align: top; width: 80px;">{time}</td>
            <td style="padding: 4px 0 4px 10px; vertical-align: top;">
              <span style="color: #333; font-weight: bold;">{title}</span><br>
              <span style="color: #999; font-size: 13px;">{location}{duration_str}</span>
            </td>
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
    due_date = job.get('updateDue', '')
    stage = job.get('stage', '')
    stage_icon = get_stage_icon(stage)
    channel_url = job.get('channelUrl', '')
    
    # Hyperlink the job title if channel URL exists
    if channel_url and channel_url != '#':
        job_title = f'<a href="{channel_url}" style="color: #333; text-decoration: none;">{job_number} — {job_name}</a>'
    else:
        job_title = f'{job_number} — {job_name}'
    
    return f'''
    <tr>
      <td style="padding: 15px 20px; border-bottom: 1px solid #eee;">
        <p style="margin: 0 0 5px 0; font-size: 16px; font-weight: bold; color: #333;">
          {job_title}
        </p>
        <p style="margin: 0 0 8px 0; font-size: 14px; color: #666; line-height: 1.4;">
          {update}
        </p>
        <p style="margin: 0; font-size: 13px; color: #999;">
          🕦 {due_date} · {stage}
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
        update_due = p.get('updateDue', '')
        stale = p.get('stale', False)
        
        stale_str = '❗ ' if stale else ''
        due_str = f" — {update_due}" if update_due else ""
        items += f'<li>{stale_str}<strong style="color: #333;">{job_number}</strong> — {job_name}{due_str}</li>'
    
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


def build_todo_email(fun_fact, meetings, work_today, work_this_week, other_projects):
    """Build complete To Do email HTML"""
    today = datetime.now().strftime('%A, %-d %B %Y')
    
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
        padding: 8px !important;
      }}
      .wrapper td {{
        padding-left: 12px !important;
        padding-right: 12px !important;
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
      <td style="padding: 20px 20px 5px 20px;">
        <p style="margin: 0; font-size: 12px; color: #999;">{today}</p>
      </td>
    </tr>
    
    {build_summary_html(fun_fact)}
    {build_meetings_html(meetings)}
    {build_section_html("WORK TODAY", work_today, "#ED1C24")}
    {build_section_html("WORK THIS WEEK", work_this_week, "#666666")}
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
        
        # Get meetings from Power Automate
        meetings = data.get('meetings', [])
        
        # Get jobs from Airtable
        jobs = get_jobs_from_airtable()
        
        # Call Claude to process and prioritise
        claude_response = call_claude(meetings, jobs)
        
        if claude_response:
            fun_fact = claude_response.get('funFact', '')
            processed_meetings = claude_response.get('meetings', [])
            work_today = claude_response.get('workToday', [])
            work_this_week = claude_response.get('workThisWeek', [])
            other_projects = claude_response.get('otherProjects', [])
        else:
            # Fallback if Claude fails
            fun_fact = ''
            processed_meetings = []
            work_today = []
            work_this_week = []
            other_projects = [{'jobNumber': j['jobNumber'], 'jobName': j['jobName']} for j in jobs]
        
        # Build HTML
        html = build_todo_email(fun_fact, processed_meetings, work_today, work_this_week, other_projects)
        
        return jsonify({
            'html': html,
            'funFact': fun_fact,
            'meetingsCount': len(processed_meetings),
            'jobsTodayCount': len(work_today),
            'jobsThisWeekCount': len(work_this_week),
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
