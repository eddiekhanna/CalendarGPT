from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv
import cv2
import numpy as np
import pytesseract
from PIL import Image
import io
import fitz  # PyMuPDF for PDF processing
import requests
import json
from prompts import SYSTEM_PROMPT, get_system_prompt_with_context
from openai import OpenAI

# Google API imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
import pickle

# Load environment variables
load_dotenv()

# Supabase configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# OpenAI API configuration
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_MODEL = "deepseek-chat"  # DeepSeek model via OpenAI API

# Google API configuration
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks'
]

# Google API credentials file path
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.pickle'

# Initialize OpenAI client
openai_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1"
) if DEEPSEEK_API_KEY else None

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# In-memory conversation history storage (in production, use a database)
conversation_history = {}

def get_conversation_history(user_id, max_messages=10):
    """Get conversation history for a user"""
    if user_id not in conversation_history:
        return []
    return conversation_history[user_id][-max_messages:]

def add_to_conversation_history(user_id, message, is_user=True):
    """Add a message to conversation history"""
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    
    conversation_history[user_id].append({
        'message': message,
        'is_user': is_user,
        'timestamp': datetime.now().isoformat()
    })
    
    # Keep only the last 20 messages to prevent memory bloat
    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

##### FILE TEXT EXTRACTION FUNCTIONS #####
def preprocess_image(image):
    """
    Preprocess image for better OCR results
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # Apply thresholding to get binary image
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Apply morphological operations to remove noise
    kernel = np.ones((1, 1), np.uint8)
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    
    return cleaned

def extract_text_from_image(image_data):
    """
    Extract text from image using Tesseract OCR with preprocessing
    """
    try:
        # Convert image data to numpy array
        nparr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Preprocess the image
        processed_image = preprocess_image(image)
        
        # Extract text using Tesseract
        text = pytesseract.image_to_string(processed_image)
        
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from image: {e}")
        return ""

def extract_text_from_pdf(pdf_data):
    """
    Extract text from PDF using PyMuPDF
    """
    try:
        # Open PDF from memory
        pdf_document = fitz.open(stream=pdf_data, filetype="pdf")
        text = ""
        
        # Extract text from each page
        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)
            text += page.get_text()
        
        pdf_document.close()
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""


##### FILE TEXT EXTRACTION ENDPOINTS #####
@app.route('/api/file/extract', methods=['POST'])
def extract_file_text():
    """
    Extract text from uploaded files and automatically process with AI
    Accepts: Any file in multipart/form-data, user_id in form data, user_message in form data (optional)
    Returns: {"response": "AI response to extracted text"}
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    uploaded_file = request.files['file']
    file_content = uploaded_file.read()
    
    # Get user_id and user_message from form data
    user_id = request.form.get('user_id')
    user_message = request.form.get('user_message', '')
    
    try:
        # Determine file type and extract text accordingly
        file_extension = uploaded_file.filename.lower().split('.')[-1]
        
        if file_extension in ['pdf']:
            # Extract text from PDF
            extracted_text = extract_text_from_pdf(file_content)
        elif file_extension in ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif']:
            # Extract text from image using Tesseract OCR
            extracted_text = extract_text_from_image(file_content)
        else:
            return jsonify({
                "error": f"Unsupported file type: {file_extension}. Supported types: PDF, JPG, PNG, BMP, TIFF"
            }), 400
        
        if not extracted_text:
            extracted_text = "No text could be extracted from this file."
        
        # Combine user message with extracted text if provided
        if user_message:
            full_text = f"User message: {user_message}\n\nFile content:\n{extracted_text}"
        else:
            full_text = extracted_text
        
        # Automatically process extracted text with AI
        ai_response = process_text_with_ai_internal(full_text, user_id)
        
        # Add to conversation history if user_id is provided
        if user_id:
            # Add the file upload as a user message
            file_message = f"Uploaded file: {uploaded_file.filename}"
            if user_message:
                file_message += f" with message: {user_message}"
            add_to_conversation_history(user_id, file_message, is_user=True)
            
            # Add AI response to conversation history
            add_to_conversation_history(user_id, ai_response, is_user=False)
        
        # If user_id is provided, also process any AI instructions
        api_result = None
        if user_id:
            api_result = process_ai_instruction(ai_response, user_id)
        
        print(f"\n📄 File: {uploaded_file.filename}")
        if user_message:
            print(f"💬 User message: {user_message}")
        print(f"📤 Extracted text: {extracted_text[:200]}...")
        print(f"🤖 AI Response: {ai_response}")
        if api_result:
            print(f"🔧 API Result: {api_result}")
        print("=" * 50)
        
        return jsonify({
            "response": ai_response,
            "api_result": api_result,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"Error processing file: {e}")
        return jsonify({
            "error": f"Failed to extract text from file: {str(e)}"
        }), 500


##### HOME ENDPOINT #####
@app.route('/')
def home():
    return jsonify({"message": "CalendarGPT API is running!"})


##### AI PROCESSING FUNCTIONS #####
def process_text_with_ai_internal(user_text, user_id=None):
    """
    Internal function to process text with AI using OpenAI API with DeepSeek model
    """
    if not DEEPSEEK_API_KEY:
        return "Error: DeepSeek API key not configured. Please set DEEPSEEK_API_KEY in your environment variables."
    
    if not openai_client:
        return "Error: OpenAI client not initialized."
    
    try:
        # Get system prompt with current date/time context
        context_prompt = get_system_prompt_with_context()
        
        # Get conversation history if user_id is provided
        conversation_context = ""
        if user_id:
            history = get_conversation_history(user_id, max_messages=8)
            if history:
                conversation_context = "\n\nPrevious conversation:\n"
                for msg in history:
                    role = "User" if msg['is_user'] else "Assistant"
                    conversation_context += f"{role}: {msg['message']}\n"
        
        # Prepare the messages for the chat completion
        messages = [
            {"role": "system", "content": context_prompt}
        ]
        
        # Add conversation context if available
        if conversation_context:
            messages.append({"role": "user", "content": conversation_context + "\nCurrent message: " + user_text})
        else:
            messages.append({"role": "user", "content": user_text})
        
        # Make request to OpenAI API with DeepSeek model
        response = openai_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=messages,
            max_tokens=256,
            temperature=0.7,
            top_p=0.9
        )
        
        # Extract the generated text from the response
        if response.choices and len(response.choices) > 0:
            generated_text = response.choices[0].message.content
            return generated_text if generated_text else "I understand your message but don't have a specific response to provide."
        else:
            return "Received an unexpected response format from the AI model."
    
    except Exception as e:
        return f"Error: Failed to get response from AI model: {str(e)}"

##### AI INITIALIZATION ENDPOINT #####
@app.route('/api/ai/init', methods=['POST'])
def initialize_ai():
    """
    Initialize AI with system prompt when user first loads the app
    Accepts: {"user_id": "user_id"}
    Returns: {"response": "Initial AI response"}
    """
    data = request.get_json()
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    
    print(f"\n🚀 Initializing AI with system prompt for user {user_id}...")
    
    # Send SESSION_START to initialize the AI with the system prompt
    ai_response = process_text_with_ai_internal("SESSION_START", user_id)
    
    print(f"🤖 Initial AI Response: {ai_response}")
    print("=" * 50)
    
    return jsonify({
        "response": ai_response,
        "user_id": user_id,
        "timestamp": datetime.now().isoformat()
    })

##### AI PROCESSING ENDPOINTS #####
@app.route('/api/ai/process', methods=['POST'])
def process_text_with_ai():
    """
    API endpoint for sending text to AI model and executing Google API calls
    Accepts: {"text": "user message or extracted PDF text", "user_id": "user_id"}
    Returns: {"response": "AI generated response"}
    """
    data = request.get_json()
    user_text = data.get('text', '')
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    
    print(f"\n📤 Received message from user {user_id}: {user_text}")
    
    # Add user message to conversation history
    add_to_conversation_history(user_id, user_text, is_user=True)
    
    # Call the same internal AI processing method
    ai_response = process_text_with_ai_internal(user_text, user_id)
    
    # Add AI response to conversation history
    add_to_conversation_history(user_id, ai_response, is_user=False)
    
    print(f"🤖 AI Response: {ai_response}")
    print("=" * 50)
    
    # Process the AI instruction and execute Google API calls
    api_result = process_ai_instruction(ai_response, user_id)
    
    if api_result.get('success'):
        print(f"✅ API Result: {api_result.get('message', 'Success')}")
    else:
        print(f"❌ API Error: {api_result.get('error', 'Unknown error')}")
    
    # Return the actual AI response to the frontend
    return jsonify({
        "response": ai_response,
        "api_result": api_result,
        "timestamp": datetime.now().isoformat()
    })

##### GOOGLE API SERVICE FUNCTIONS #####
@app.route('/api/auth/check-credentials', methods=['GET'])
def check_google_credentials():
    """
    Check if a user has Google credentials stored
    """
    user_id = request.args.get('user_id')
    
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    
    if not supabase:
        return jsonify({"error": "Supabase client not configured"}), 500
    
    try:
        response = supabase.table('google_credentials').select('*').eq('user_id', user_id).execute()
        
        has_credentials = len(response.data) > 0
        
        return jsonify({
            "has_credentials": has_credentials,
            "credentials_count": len(response.data),
            "user_id": user_id
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to check credentials: {str(e)}"}), 500

def get_google_credentials(user_id):
    """
    Get Google API credentials for a specific user from Supabase
    """
    if not supabase:
        return None, "Supabase client not configured"
    
    try:
        print(f"🔍 Looking for Google credentials for user: {user_id}")
        
        # Get user's Google credentials from Supabase
        response = supabase.table('google_credentials').select('*').eq('user_id', user_id).execute()
        
        print(f"📊 Database response: {response}")
        print(f"📊 Response data: {response.data}")
        
        if not response.data:
            return None, f"No Google credentials found for user {user_id}"
        
        credentials_data = response.data[0]
        print(f"🔑 Found credentials: {credentials_data}")
        
        # Create credentials object from stored data
        creds = Credentials(
            token=credentials_data['access_token'],
            refresh_token=credentials_data['refresh_token'],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=credentials_data['client_id'],
            scopes=credentials_data['scopes']
        )
        
        # Refresh token if expired
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                
                # Update the stored access token
                supabase.table('google_credentials').update({
                    'access_token': creds.token,
                    'expiry': creds.expiry.isoformat() if creds.expiry else None
                }).eq('user_id', user_id).execute()
                
            except Exception as e:
                return None, f"Failed to refresh token: {str(e)}"
        
        return creds, None
        
    except Exception as e:
        print(f"❌ Error getting Google credentials: {e}")
        return None, f"Failed to get Google credentials: {str(e)}"

def get_calendar_service(user_id):
    """
    Get Google Calendar service for a specific user
    """
    creds, error = get_google_credentials(user_id)
    if error:
        return None, error
    
    try:
        service = build('calendar', 'v3', credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to create Calendar service: {str(e)}"

def get_tasks_service(user_id):
    """
    Get Google Tasks service for a specific user
    """
    creds, error = get_google_credentials(user_id)
    if error:
        return None, error
    
    try:
        service = build('tasks', 'v1', credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to create Tasks service: {str(e)}"

##### CALENDAR API ENDPOINTS #####

#### WHAT IT DOES: Creates a new calendar event ####
@app.route('/api/calendar/events', methods=['POST'])
def create_calendar_event():
    """
    Create a new calendar event
    """
    try:
        data = request.get_json()
        service, error = get_calendar_service()
        if error:
            return jsonify({"error": error}), 500
        
        # Extract event data from AI instruction
        event_data = {
            'summary': data.get('title', 'Untitled Event'),
            'description': data.get('description'),
            'location': data.get('location'),
        }
        
        # Handle start time
        if data.get('datetime_start'):
            event_data['start'] = {
                'dateTime': data['datetime_start'],
                'timeZone': 'America/Chicago'  # Default timezone
            }
        elif data.get('date'):
            event_data['start'] = {
                'date': data['date']
            }
        
        # Handle end time
        if data.get('datetime_end'):
            event_data['end'] = {
                'dateTime': data['datetime_end'],
                'timeZone': 'America/Chicago'
            }
        elif data.get('date') and not data.get('datetime_start'):
            # For all-day events, end date should be the day after
            from datetime import datetime, timedelta
            start_date = datetime.strptime(data['date'], '%Y-%m-%d')
            end_date = start_date + timedelta(days=1)
            event_data['end'] = {
                'date': end_date.strftime('%Y-%m-%d')
            }
        
        # Handle recurrence
        if data.get('recurrence'):
            recurrence_obj = data['recurrence']
            
            # Convert AI recurrence object to RFC 5545 format
            rrule_parts = []
            
            if recurrence_obj.get('freq'):
                rrule_parts.append(f"FREQ={recurrence_obj['freq'].upper()}")
            
            if recurrence_obj.get('interval'):
                rrule_parts.append(f"INTERVAL={recurrence_obj['interval']}")
            
            if recurrence_obj.get('until'):
                # Convert date to RFC 5545 format (YYYYMMDD)
                until_date = recurrence_obj['until']
                if 'T' in until_date:
                    # It's a datetime, convert to date only
                    until_date = until_date.split('T')[0]
                # Convert YYYY-MM-DD to YYYYMMDD
                until_date = until_date.replace('-', '')
                rrule_parts.append(f"UNTIL={until_date}")
            
            if recurrence_obj.get('byweekday'):
                days = recurrence_obj['byweekday']
                day_map = {
                    'MO': 'MO', 'TU': 'TU', 'WE': 'WE', 'TH': 'TH', 
                    'FR': 'FR', 'SA': 'SA', 'SU': 'SU'
                }
                day_list = []
                for day in days:
                    if day in day_map:
                        day_list.append(day_map[day])
                if day_list:
                    rrule_parts.append(f"BYDAY={','.join(day_list)}")
            
            # Create the RRULE string
            if rrule_parts:
                rrule = f"RRULE:{';'.join(rrule_parts)}"
                event_data['recurrence'] = [rrule]
            else:
                # Fallback to simple daily recurrence
                event_data['recurrence'] = ["RRULE:FREQ=DAILY"]
        
        # Handle reminders
        if data.get('reminders'):
            event_data['reminders'] = {
                'useDefault': False,
                'overrides': []
            }
            for reminder in data['reminders']:
                event_data['reminders']['overrides'].append({
                    'method': 'popup',
                    'minutes': int(reminder.replace('PT', '').replace('M', ''))
                })
        
        # Debug: Print the event data being sent
        print(f"🎯 Creating event with data: {json.dumps(event_data, indent=2)}")
        
        # Create the event
        event = service.events().insert(
            calendarId='primary',
            body=event_data,
            sendUpdates='all'
        ).execute()
        
        return jsonify({
            "success": True,
            "event": event,
            "message": f"Event '{event_data['summary']}' created successfully"
        })
        
    except HttpError as error:
        return jsonify({"error": f"Calendar API error: {error}"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to create event: {str(e)}"}), 500

#### WHAT IT DOES: Updates an existing calendar event ####
@app.route('/api/calendar/events/<event_id>', methods=['PUT'])
def update_calendar_event(event_id):
    """
    Update an existing calendar event
    """
    try:
        data = request.get_json()
        service, error = get_calendar_service()
        if error:
            return jsonify({"error": error}), 500
        
        # Build update data similar to create
        event_data = {}
        if data.get('title'):
            event_data['summary'] = data['title']
        if data.get('description'):
            event_data['description'] = data['description']
        if data.get('location'):
            event_data['location'] = data['location']
        
        # Handle start/end times
        if data.get('datetime_start'):
            event_data['start'] = {
                'dateTime': data['datetime_start'],
                'timeZone': 'America/Chicago'
            }
        elif data.get('date'):
            event_data['start'] = {
                'date': data['date']
            }
        
        if data.get('datetime_end'):
            event_data['end'] = {
                'dateTime': data['datetime_end'],
                'timeZone': 'America/Chicago'
            }
        
        # Update the event
        event = service.events().update(
            calendarId='primary',
            eventId=event_id,
            body=event_data,
            sendUpdates='all'
        ).execute()
        
        return jsonify({
            "success": True,
            "event": event,
            "message": f"Event updated successfully"
        })
        
    except HttpError as error:
        return jsonify({"error": f"Calendar API error: {error}"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to update event: {str(e)}"}), 500

#### WHAT IT DOES: Deletes a calendar event ####
@app.route('/api/calendar/events/<event_id>', methods=['DELETE'])
def delete_calendar_event(event_id):
    """
    Delete a calendar event
    """
    try:
        service, error = get_calendar_service()
        if error:
            return jsonify({"error": error}), 500
        
        service.events().delete(
            calendarId='primary',
            eventId=event_id,
            sendUpdates='all'
        ).execute()
        
        return jsonify({
            "success": True,
            "message": "Event deleted successfully"
        })
        
    except HttpError as error:
        return jsonify({"error": f"Calendar API error: {error}"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to delete event: {str(e)}"}), 500

#### WHAT IT DOES: Lists calendar events for a date range ####
@app.route('/api/calendar/events', methods=['GET'])
def list_calendar_events():
    """
    List calendar events for a date range
    """
    try:
        service, error = get_calendar_service()
        if error:
            return jsonify({"error": error}), 500
        
        # Get query parameters
        time_min = request.args.get('timeMin')
        time_max = request.args.get('timeMax')
        date = request.args.get('date')
        
        # If date is provided, convert to time range
        if date:
            time_min = f"{date}T00:00:00Z"
            time_max = f"{date}T23:59:59Z"
        
        # List events
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        return jsonify({
            "success": True,
            "events": events,
            "count": len(events)
        })
        
    except HttpError as error:
        return jsonify({"error": f"Calendar API error: {error}"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to list events: {str(e)}"}), 500

##### TASKS API ENDPOINTS #####

#### WHAT IT DOES: Creates a new task ####
@app.route('/api/tasks', methods=['POST'])
def create_task():
    """
    Create a new task
    """
    try:
        data = request.get_json()
        service, error = get_tasks_service()
        if error:
            return jsonify({"error": error}), 500
        
        # Get default task list (usually "@default")
        tasklists = service.tasklists().list().execute()
        tasklist_id = tasklists['items'][0]['id'] if tasklists['items'] else '@default'
        
        # Build task data
        task_data = {
            'title': data.get('title', 'Untitled Task'),
            'notes': data.get('description'),
        }
        
        # Handle due date
        if data.get('datetime_start'):
            task_data['due'] = data['datetime_start']
        elif data.get('date'):
            task_data['due'] = data['date']
        
        # Create the task
        task = service.tasks().insert(
            tasklist=tasklist_id,
            body=task_data
        ).execute()
        
        return jsonify({
            "success": True,
            "task": task,
            "message": f"Task '{task_data['title']}' created successfully"
        })
        
    except HttpError as error:
        return jsonify({"error": f"Tasks API error: {error}"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to create task: {str(e)}"}), 500

#### WHAT IT DOES: Updates an existing task ####
@app.route('/api/tasks/<task_id>', methods=['PUT'])
def update_task(task_id):
    """
    Update an existing task
    """
    try:
        data = request.get_json()
        service, error = get_tasks_service()
        if error:
            return jsonify({"error": error}), 500
        
        # Get default task list
        tasklists = service.tasklists().list().execute()
        tasklist_id = tasklists['items'][0]['id'] if tasklists['items'] else '@default'
        
        # Build update data
        task_data = {}
        if data.get('title'):
            task_data['title'] = data['title']
        if data.get('description'):
            task_data['notes'] = data['description']
        if data.get('datetime_start'):
            task_data['due'] = data['datetime_start']
        elif data.get('date'):
            task_data['due'] = data['date']
        
        # Update the task
        task = service.tasks().update(
            tasklist=tasklist_id,
            task=task_id,
            body=task_data
        ).execute()
        
        return jsonify({
            "success": True,
            "task": task,
            "message": "Task updated successfully"
        })
        
    except HttpError as error:
        return jsonify({"error": f"Tasks API error: {error}"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to update task: {str(e)}"}), 500

#### WHAT IT DOES: Deletes a task ####
@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    """
    Delete a task
    """
    try:
        service, error = get_tasks_service()
        if error:
            return jsonify({"error": error}), 500
        
        # Get default task list
        tasklists = service.tasklists().list().execute()
        tasklist_id = tasklists['items'][0]['id'] if tasklists['items'] else '@default'
        
        service.tasks().delete(
            tasklist=tasklist_id,
            task=task_id
        ).execute()
        
        return jsonify({
            "success": True,
            "message": "Task deleted successfully"
        })
        
    except HttpError as error:
        return jsonify({"error": f"Tasks API error: {error}"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to delete task: {str(e)}"}), 500

#### WHAT IT DOES: Lists tasks for a date range ####
@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    """
    List tasks for a date range
    """
    try:
        service, error = get_tasks_service()
        if error:
            return jsonify({"error": error}), 500
        
        # Get default task list
        tasklists = service.tasklists().list().execute()
        tasklist_id = tasklists['items'][0]['id'] if tasklists['items'] else '@default'
        
        # Get query parameters
        due_min = request.args.get('dueMin')
        due_max = request.args.get('dueMax')
        date = request.args.get('date')
        
        # If date is provided, convert to due range
        if date:
            due_min = f"{date}T00:00:00Z"
            due_max = f"{date}T23:59:59Z"
        
        # List tasks
        tasks_result = service.tasks().list(
            tasklist=tasklist_id,
            showCompleted=False,
            dueMin=due_min,
            dueMax=due_max
        ).execute()
        
        tasks = tasks_result.get('items', [])
        
        return jsonify({
            "success": True,
            "tasks": tasks,
            "count": len(tasks)
        })
        
    except HttpError as error:
        return jsonify({"error": f"Tasks API error: {error}"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to list tasks: {str(e)}"}), 500

##### AI RESPONSE PROCESSING #####

def clean_json_string(json_str):
    """
    Clean up JSON string to handle common formatting issues from AI responses
    """
    import re
    
    # Remove trailing commas before closing braces and brackets
    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
    
    # Remove trailing commas in object properties
    json_str = re.sub(r',(\s*})', r'\1', json_str)
    
    # Fix common quote issues
    json_str = json_str.replace('"', '"').replace('"', '"')
    json_str = json_str.replace(''', "'").replace(''', "'")
    
    # Remove any extra whitespace around the JSON
    json_str = json_str.strip()
    
    return json_str

#### WHAT IT DOES: Parses AI response and executes Google API calls ####
def process_ai_instruction(ai_response, user_id):
    """
    Parse the AI's structured response and execute the appropriate Google API call
    """
    try:
        # Extract the instruction JSON from the AI response
        import re
        import json
        
        # Find the instruction block with a more robust regex
        instruction_match = re.search(r'instruction:\s*(\{.*\})', ai_response, re.DOTALL)
        if not instruction_match:
            return {"error": "No instruction found in AI response"}
        
        instruction_str = instruction_match.group(1)
        
        # Clean up the JSON string - remove trailing commas and fix formatting
        instruction_str = clean_json_string(instruction_str)
        
        # Parse the instruction JSON
        try:
            instruction = json.loads(instruction_str)
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {e}")
            print(f"Instruction string: {instruction_str}")
            print(f"Error position: line {e.lineno}, column {e.colno}")
            print(f"Error message: {e.msg}")
            
            # Try to extract a valid JSON object from the malformed string
            try:
                # Find the first complete JSON object
                brace_count = 0
                start_pos = instruction_str.find('{')
                if start_pos != -1:
                    for i in range(start_pos, len(instruction_str)):
                        if instruction_str[i] == '{':
                            brace_count += 1
                        elif instruction_str[i] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                # Found complete JSON object
                                valid_json = instruction_str[start_pos:i+1]
                                instruction = json.loads(valid_json)
                                print(f"Successfully parsed partial JSON: {valid_json}")
                                break
                    else:
                        return {"error": f"Failed to parse instruction JSON: Incomplete JSON object"}
                else:
                    return {"error": f"Failed to parse instruction JSON: No JSON object found"}
            except json.JSONDecodeError as e2:
                return {"error": f"Failed to parse instruction JSON: {e2}"}
        
        action = instruction.get('action')
        item_type = instruction.get('item_type')
        
        print(f"🔍 Parsed instruction: {action} {item_type}")
        
        # Handle different actions
        if action == 'greeting':
            return {"success": True, "message": "Greeting processed"}
        
        elif action == 'create':
            if item_type == 'event':
                return create_calendar_event_from_instruction(instruction, user_id)
            elif item_type == 'task':
                return create_task_from_instruction(instruction, user_id)
        
        elif action == 'update':
            if item_type == 'event':
                return update_calendar_event_from_instruction(instruction, user_id)
            elif item_type == 'task':
                return update_task_from_instruction(instruction, user_id)
        
        elif action == 'delete':
            if item_type == 'event':
                return delete_calendar_event_from_instruction(instruction, user_id)
            elif item_type == 'task':
                return delete_task_from_instruction(instruction, user_id)
        
        elif action == 'find_and_delete':
            if item_type == 'event':
                return find_and_delete_calendar_event_from_instruction(instruction, user_id)
            elif item_type == 'task':
                return find_and_delete_task_from_instruction(instruction, user_id)
        
        elif action == 'query':
            if item_type == 'event':
                return query_calendar_events_from_instruction(instruction, user_id)
            elif item_type == 'task':
                return query_tasks_from_instruction(instruction, user_id)
        
        elif action == 'clarification_needed':
            return {"success": True, "message": "Clarification needed", "clarification": True}
        
        else:
            return {"error": f"Unknown action: {action}"}
    
    except Exception as e:
        return {"error": f"Failed to process AI instruction: {str(e)}"}

def create_calendar_event_from_instruction(instruction, user_id):
    """Create calendar event from AI instruction"""
    try:
        service, error = get_calendar_service(user_id)
        if error:
            return {"error": error}
        
        # Build event data
        event_data = {
            'summary': instruction.get('title', 'Untitled Event'),
            'description': instruction.get('description'),
            'location': instruction.get('location'),
        }
        
        # Handle start time
        if instruction.get('datetime_start'):
            event_data['start'] = {
                'dateTime': instruction['datetime_start'],
                'timeZone': 'America/Chicago'
            }
        elif instruction.get('date'):
            event_data['start'] = {
                'date': instruction['date']
            }
        
        # Handle end time
        if instruction.get('datetime_end'):
            event_data['end'] = {
                'dateTime': instruction['datetime_end'],
                'timeZone': 'America/Chicago'
            }
        elif instruction.get('date') and not instruction.get('datetime_start'):
            # For all-day events
            from datetime import datetime, timedelta
            start_date = datetime.strptime(instruction['date'], '%Y-%m-%d')
            end_date = start_date + timedelta(days=1)
            event_data['end'] = {
                'date': end_date.strftime('%Y-%m-%d')
            }
        
        # Handle recurrence
        if instruction.get('recurrence'):
            recurrence_obj = instruction['recurrence']
            
            # Convert AI recurrence object to RFC 5545 format
            rrule_parts = []
            
            if recurrence_obj.get('freq'):
                rrule_parts.append(f"FREQ={recurrence_obj['freq'].upper()}")
            
            if recurrence_obj.get('interval'):
                rrule_parts.append(f"INTERVAL={recurrence_obj['interval']}")
            
            if recurrence_obj.get('until'):
                # Convert date to RFC 5545 format (YYYYMMDD)
                until_date = recurrence_obj['until']
                if 'T' in until_date:
                    # It's a datetime, convert to date only
                    until_date = until_date.split('T')[0]
                # Convert YYYY-MM-DD to YYYYMMDD
                until_date = until_date.replace('-', '')
                rrule_parts.append(f"UNTIL={until_date}")
            
            if recurrence_obj.get('byweekday'):
                days = recurrence_obj['byweekday']
                day_map = {
                    'MO': 'MO', 'TU': 'TU', 'WE': 'WE', 'TH': 'TH', 
                    'FR': 'FR', 'SA': 'SA', 'SU': 'SU'
                }
                day_list = []
                for day in days:
                    if day in day_map:
                        day_list.append(day_map[day])
                if day_list:
                    rrule_parts.append(f"BYDAY={','.join(day_list)}")
            
            # Create the RRULE string
            if rrule_parts:
                rrule = f"RRULE:{';'.join(rrule_parts)}"
                event_data['recurrence'] = [rrule]
            else:
                # Fallback to simple daily recurrence
                event_data['recurrence'] = ["RRULE:FREQ=DAILY"]
        
        # Handle reminders
        if instruction.get('reminders'):
            event_data['reminders'] = {
                'useDefault': False,
                'overrides': []
            }
            for reminder in instruction['reminders']:
                event_data['reminders']['overrides'].append({
                    'method': 'popup',
                    'minutes': int(reminder.replace('PT', '').replace('M', ''))
                })
        
        # Debug: Print the event data being sent
        print(f"🎯 Creating event with data: {json.dumps(event_data, indent=2)}")
        
        # Create the event
        event = service.events().insert(
            calendarId='primary',
            body=event_data,
            sendUpdates='all'
        ).execute()
        
        return {
            "success": True,
            "message": f"Event '{event_data['summary']}' created successfully",
            "event": event
        }
        
    except Exception as e:
        return {"error": f"Failed to create calendar event: {str(e)}"}

def create_task_from_instruction(instruction, user_id):
    """Create task from AI instruction"""
    try:
        service, error = get_tasks_service(user_id)
        if error:
            return {"error": error}
        
        # Get default task list
        tasklists = service.tasklists().list().execute()
        tasklist_id = tasklists['items'][0]['id'] if tasklists['items'] else '@default'
        
        # Build task data
        task_data = {
            'title': instruction.get('title', 'Untitled Task'),
            'notes': instruction.get('description'),
        }
        
        # Handle due date
        if instruction.get('datetime_start'):
            task_data['due'] = instruction['datetime_start']
        elif instruction.get('date'):
            task_data['due'] = instruction['date']
        
        # Create the task
        task = service.tasks().insert(
            tasklist=tasklist_id,
            body=task_data
        ).execute()
        
        return {
            "success": True,
            "message": f"Task '{task_data['title']}' created successfully",
            "task": task
        }
        
    except Exception as e:
        return {"error": f"Failed to create task: {str(e)}"}

def query_calendar_events_from_instruction(instruction, user_id):
    """Query calendar events from AI instruction"""
    try:
        service, error = get_calendar_service(user_id)
        if error:
            return {"error": error}
        
        # Build query parameters
        time_min = instruction.get('datetime_start')
        time_max = instruction.get('datetime_end')
        date = instruction.get('date')
        
        # If date is provided, convert to time range
        if date:
            time_min = f"{date}T00:00:00Z"
            time_max = f"{date}T23:59:59Z"
        
        # List events
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # Format events for display
        if events:
            event_list = []
            for event in events:
                start_date = event.get('start', {})
                if start_date.get('dateTime'):
                    # Event with specific time
                    start_time = datetime.fromisoformat(start_date['dateTime'].replace('Z', '+00:00'))
                    formatted_time = start_time.strftime('%m/%d/%Y at %I:%M %p')
                    event_list.append(f"• {event.get('summary', 'Untitled Event')} ({formatted_time})")
                elif start_date.get('date'):
                    # All-day event
                    start_date_obj = datetime.fromisoformat(start_date['date'])
                    formatted_date = start_date_obj.strftime('%m/%d/%Y')
                    event_list.append(f"• {event.get('summary', 'Untitled Event')} (All day - {formatted_date})")
                else:
                    event_list.append(f"• {event.get('summary', 'Untitled Event')} (No date specified)")
            
            formatted_events = '\n'.join(event_list)
            formatted_response = f"📅 **Your Events:**\n\n{formatted_events}"
        else:
            formatted_response = "📅 **Your Events:**\n\nNo events found for the specified time period."
        
        return {
            "success": True,
            "message": f"Found {len(events)} events",
            "events": events,
            "count": len(events),
            "formatted_response": formatted_response
        }
        
    except Exception as e:
        return {"error": f"Failed to query calendar events: {str(e)}"}

def query_tasks_from_instruction(instruction, user_id):
    """Query tasks from AI instruction"""
    try:
        service, error = get_tasks_service(user_id)
        if error:
            return {"error": error}
        
        # Get default task list
        tasklists = service.tasklists().list().execute()
        tasklist_id = tasklists['items'][0]['id'] if tasklists['items'] else '@default'
        
        # Build query parameters
        due_min = instruction.get('datetime_start')
        due_max = instruction.get('datetime_end')
        date = instruction.get('date')
        
        # If date is provided, convert to due range
        if date:
            due_min = f"{date}T00:00:00Z"
            due_max = f"{date}T23:59:59Z"
        
        # List tasks
        tasks_result = service.tasks().list(
            tasklist=tasklist_id,
            showCompleted=False,
            dueMin=due_min,
            dueMax=due_max
        ).execute()
        
        tasks = tasks_result.get('items', [])
        
        # Format tasks for display
        if tasks:
            task_list = []
            for task in tasks:
                due_date = task.get('due')
                if due_date:
                    # Task with due date
                    due_date_obj = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                    formatted_date = due_date_obj.strftime('%m/%d/%Y')
                    task_list.append(f"• {task.get('title', 'Untitled Task')} (Due: {formatted_date})")
                else:
                    # Task without due date
                    task_list.append(f"• {task.get('title', 'Untitled Task')} (Due: No due date)")
            
            formatted_tasks = '\n'.join(task_list)
            formatted_response = f"📋 **Your Tasks:**\n\n{formatted_tasks}"
        else:
            formatted_response = "📋 **Your Tasks:**\n\nNo tasks found for the specified time period."
        
        return {
            "success": True,
            "message": f"Found {len(tasks)} tasks",
            "tasks": tasks,
            "count": len(tasks),
            "formatted_response": formatted_response
        }
        
    except Exception as e:
        return {"error": f"Failed to query tasks: {str(e)}"}

def update_calendar_event_from_instruction(instruction, user_id):
    """Update calendar event from AI instruction"""
    # This would need the event ID to update
    return {"error": "Event update requires event ID - not implemented yet"}

def update_task_from_instruction(instruction, user_id):
    """Update task from AI instruction"""
    # This would need the task ID to update
    return {"error": "Task update requires task ID - not implemented yet"}

def delete_calendar_event_from_instruction(instruction, user_id):
    """Delete calendar event from AI instruction"""
    try:
        service, error = get_calendar_service(user_id)
        if error:
            return {"error": error}
        
        # Get the event ID from the instruction
        event_id = instruction.get('event_id')
        if not event_id:
            return {"error": "Event ID is required for deletion"}
        
        # Delete the event
        service.events().delete(
            calendarId='primary',
            eventId=event_id,
            sendUpdates='all'
        ).execute()
        
        return {
            "success": True,
            "message": f"Event deleted successfully",
            "event_id": event_id
        }
        
    except HttpError as error:
        return {"error": f"Calendar API error: {error}"}
    except Exception as e:
        return {"error": f"Failed to delete calendar event: {str(e)}"}

def delete_task_from_instruction(instruction, user_id):
    """Delete task from AI instruction"""
    try:
        service, error = get_tasks_service(user_id)
        if error:
            return {"error": error}
        
        # Get the task ID from the instruction
        task_id = instruction.get('task_id')
        if not task_id:
            return {"error": "Task ID is required for deletion"}
        
        # Get default task list
        tasklists = service.tasklists().list().execute()
        tasklist_id = tasklists['items'][0]['id'] if tasklists['items'] else '@default'
        
        # Delete the task
        service.tasks().delete(
            tasklist=tasklist_id,
            task=task_id
        ).execute()
        
        return {
            "success": True,
            "message": f"Task deleted successfully",
            "task_id": task_id
        }
        
    except HttpError as error:
        return {"error": f"Tasks API error: {error}"}
    except Exception as e:
        return {"error": f"Failed to delete task: {str(e)}"}

def find_and_delete_task_from_instruction(instruction, user_id):
    """Find and delete task from AI instruction by description"""
    try:
        service, error = get_tasks_service(user_id)
        if error:
            return {"error": error}
        
        # Get default task list
        tasklists = service.tasklists().list().execute()
        tasklist_id = tasklists['items'][0]['id'] if tasklists['items'] else '@default'
        
        # Get all tasks
        tasks_result = service.tasks().list(
            tasklist=tasklist_id,
            showCompleted=False
        ).execute()
        
        tasks = tasks_result.get('items', [])
        
        if not tasks:
            return {
                "success": True,
                "message": "No tasks found to delete.",
                "formatted_response": "📋 **No tasks found**\n\nThere are no tasks available to delete."
            }
        
        # Get the search description from the instruction
        search_description = instruction.get('title', '').lower()
        
        # Find matching tasks
        matching_tasks = []
        for task in tasks:
            task_title = task.get('title', '').lower()
            if search_description in task_title or task_title in search_description:
                matching_tasks.append(task)
        
        if not matching_tasks:
            # No matches found, show all tasks and ask user to specify
            task_list = []
            for task in tasks:
                due_date = task.get('due')
                if due_date:
                    due_date_obj = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                    formatted_date = due_date_obj.strftime('%m/%d/%Y')
                    task_list.append(f"• {task.get('title', 'Untitled Task')} (Due: {formatted_date})")
                else:
                    task_list.append(f"• {task.get('title', 'Untitled Task')} (Due: No due date)")
            
            formatted_tasks = '\n'.join(task_list)
            return {
                "success": True,
                "message": f"No tasks found matching '{search_description}'. Here are all your tasks:",
                "tasks": tasks,
                "formatted_response": f"❌ **No matching tasks found**\n\nI couldn't find any tasks matching '{search_description}'. Here are all your tasks:\n\n{formatted_tasks}\n\nPlease specify which task you'd like to delete."
            }
        
        if len(matching_tasks) == 1:
            # Exactly one match found, delete it
            task_to_delete = matching_tasks[0]
            task_title = task_to_delete.get('title', 'Untitled Task')
            
            # Delete the task
            service.tasks().delete(
                tasklist=tasklist_id,
                task=task_to_delete['id']
            ).execute()
            
            return {
                "success": True,
                "message": f"Task '{task_title}' deleted successfully.",
                "formatted_response": f"✅ **Task Deleted**\n\nSuccessfully deleted: {task_title}"
            }
        
        else:
            # Multiple matches found, show them and ask user to specify
            task_list = []
            for task in matching_tasks:
                due_date = task.get('due')
                if due_date:
                    due_date_obj = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                    formatted_date = due_date_obj.strftime('%m/%d/%Y')
                    task_list.append(f"• {task.get('title', 'Untitled Task')} (Due: {formatted_date})")
                else:
                    task_list.append(f"• {task.get('title', 'Untitled Task')} (Due: No due date)")
            
            formatted_tasks = '\n'.join(task_list)
            return {
                "success": True,
                "message": f"Found {len(matching_tasks)} tasks matching '{search_description}'. Please specify which one to delete:",
                "tasks": matching_tasks,
                "formatted_response": f"🔍 **Multiple matches found**\n\nFound {len(matching_tasks)} tasks matching '{search_description}':\n\n{formatted_tasks}\n\nPlease specify which task you'd like to delete by providing more details."
            }
        
    except Exception as e:
        return {"error": f"Failed to find and delete task: {str(e)}"}

def find_and_delete_calendar_event_from_instruction(instruction, user_id):
    """Find and delete calendar event from AI instruction by description"""
    try:
        service, error = get_calendar_service(user_id)
        if error:
            return {"error": error}
        
        # Get all events for the next 30 days
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        time_min = now.isoformat() + 'Z'
        time_max = (now + timedelta(days=30)).isoformat() + 'Z'
        
        # List events
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return {
                "success": True,
                "message": "No events found to delete.",
                "formatted_response": "📅 **No events found**\n\nThere are no events available to delete."
            }
        
        # Get the search description from the instruction
        search_description = instruction.get('title', '').lower()
        
        # Get date/time constraints from instruction
        instruction_date = instruction.get('date')
        instruction_datetime_start = instruction.get('datetime_start')
        instruction_time = instruction.get('time')
        
        # Find matching events
        matching_events = []
        for event in events:
            event_title = event.get('summary', '').lower()
            title_matches = search_description in event_title or event_title in search_description
            
            if title_matches:
                # Check if date/time also matches
                event_start = event.get('start', {})
                event_datetime = event_start.get('dateTime')
                event_date = event_start.get('date')
                
                date_matches = True  # Default to true if no date specified in instruction
                
                if instruction_date:
                    # User specified a date
                    if event_date:
                        # Event is all-day, compare dates
                        date_matches = event_date == instruction_date
                    elif event_datetime:
                        # Event has time, compare date part
                        event_date_part = event_datetime.split('T')[0]
                        date_matches = event_date_part == instruction_date
                
                elif instruction_datetime_start:
                    # User specified a datetime
                    if event_datetime:
                        # Compare datetime (allow for some flexibility in time)
                        event_dt = datetime.fromisoformat(event_datetime.replace('Z', '+00:00'))
                        instruction_dt = datetime.fromisoformat(instruction_datetime_start.replace('Z', '+00:00'))
                        # Allow 1 hour difference for flexibility
                        time_diff = abs((event_dt - instruction_dt).total_seconds())
                        date_matches = time_diff <= 3600  # 1 hour in seconds
                
                elif instruction_time:
                    # User specified just a time
                    if event_datetime:
                        event_dt = datetime.fromisoformat(event_datetime.replace('Z', '+00:00'))
                        event_time_str = event_dt.strftime('%H:%M')
                        date_matches = event_time_str == instruction_time
                
                if date_matches:
                    matching_events.append(event)
        
        if not matching_events:
            # No matches found, show all events and ask user to specify
            event_list = []
            for event in events:
                start_date = event.get('start', {})
                if start_date.get('dateTime'):
                    start_time = datetime.fromisoformat(start_date['dateTime'].replace('Z', '+00:00'))
                    formatted_time = start_time.strftime('%m/%d/%Y at %I:%M %p')
                    event_list.append(f"• {event.get('summary', 'Untitled Event')} ({formatted_time})")
                elif start_date.get('date'):
                    start_date_obj = datetime.fromisoformat(start_date['date'])
                    formatted_date = start_date_obj.strftime('%m/%d/%Y')
                    event_list.append(f"• {event.get('summary', 'Untitled Event')} (All day - {formatted_date})")
                else:
                    event_list.append(f"• {event.get('summary', 'Untitled Event')} (No date specified)")
            
            formatted_events = '\n'.join(event_list)
            return {
                "success": True,
                "message": f"No events found matching '{search_description}'. Here are all your events:",
                "events": events,
                "formatted_response": f"❌ **No matching events found**\n\nI couldn't find any events matching '{search_description}'. Here are your upcoming events:\n\n{formatted_events}\n\nPlease specify which event you'd like to delete."
            }
        
        if len(matching_events) == 1:
            # Exactly one match found, delete it
            event_to_delete = matching_events[0]
            event_title = event_to_delete.get('summary', 'Untitled Event')
            
            # Delete the event
            service.events().delete(
                calendarId='primary',
                eventId=event_to_delete['id'],
                sendUpdates='all'
            ).execute()
            
            return {
                "success": True,
                "message": f"Event '{event_title}' deleted successfully.",
                "formatted_response": f"✅ **Event Deleted**\n\nSuccessfully deleted: {event_title}"
            }
        
        else:
            # Multiple matches found, show them and ask user to specify
            event_list = []
            for event in matching_events:
                start_date = event.get('start', {})
                if start_date.get('dateTime'):
                    start_time = datetime.fromisoformat(start_date['dateTime'].replace('Z', '+00:00'))
                    formatted_time = start_time.strftime('%m/%d/%Y at %I:%M %p')
                    event_list.append(f"• {event.get('summary', 'Untitled Event')} ({formatted_time})")
                elif start_date.get('date'):
                    start_date_obj = datetime.fromisoformat(start_date['date'])
                    formatted_date = start_date_obj.strftime('%m/%d/%Y')
                    event_list.append(f"• {event.get('summary', 'Untitled Event')} (All day - {formatted_date})")
                else:
                    event_list.append(f"• {event.get('summary', 'Untitled Event')} (No date specified)")
            
            formatted_events = '\n'.join(event_list)
            return {
                "success": True,
                "message": f"Found {len(matching_events)} events matching '{search_description}'. Please specify which one to delete:",
                "events": matching_events,
                "formatted_response": f"🔍 **Multiple matches found**\n\nFound {len(matching_events)} events matching '{search_description}':\n\n{formatted_events}\n\nPlease specify which event you'd like to delete by providing more details."
            }
        
    except Exception as e:
        return {"error": f"Failed to find and delete calendar event: {str(e)}"}

if __name__ == '__main__':  
    
    app.run(debug=True, host='0.0.0.0', port=5001)


