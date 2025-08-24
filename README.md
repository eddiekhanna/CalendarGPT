# CalendarGPT

A smart calendar assistant that can extract text from PDFs and images, then create Google Calendar events based on the extracted information.

## Features

- 📄 **PDF Text Extraction**: Extract text from PDF documents using PyMuPDF
- 📸 **Image OCR**: Extract text from images and screenshots using Tesseract OCR
- 📅 **Google Calendar Integration**: Create calendar events from extracted text
- 🎨 **Modern UI**: Beautiful React frontend with Tailwind CSS
- 🔐 **Authentication**: Secure user authentication with Supabase

## Tech Stack

### Backend

- **Python Flask**: Web server and API
- **PyMuPDF**: PDF text extraction
- **Tesseract OCR**: Image text extraction
- **OpenCV**: Image preprocessing
- **Google Calendar API**: Calendar event creation
- **Supabase**: Database and authentication

### Frontend

- **React**: User interface
- **TypeScript**: Type safety
- **Tailwind CSS**: Styling
- **Vite**: Build tool
- **Supabase Client**: Authentication and data management

## Prerequisites

- Python 3.8+
- Node.js 16+
- Tesseract OCR
- Google Calendar API credentials
- Supabase account

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/CalendarGPT.git
cd CalendarGPT
```

### 2. Backend Setup

```bash
cd backend
pip install -r requirements.txt
```

### 3. Frontend Setup

```bash
cd frontend
npm install
```

### 4. Environment Configuration

#### Backend (.env file in backend directory)

```env
GOOGLE_APPLICATION_CREDENTIALS=path/to/your/credentials.json
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
```

#### Frontend (.env file in frontend directory)

```env
VITE_SUPABASE_URL=your_supabase_url
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
```

### 5. Google Calendar API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Google Calendar API
4. Create service account credentials
5. Download the JSON credentials file
6. Place it in the backend directory as `credentials.json`

### 6. Supabase Setup

1. Create a Supabase project
2. Run the SQL schema from `backend/supabase_schema.sql`
3. Get your project URL and anon key from settings

## Usage

### Development

#### Start Backend

```bash
cd backend
python app.py
```

#### Start Frontend

```bash
cd frontend
npm run dev
```

### Production

#### Build Frontend

```bash
cd frontend
npm run build
```

#### Deploy Backend

Deploy the Flask app to your preferred hosting service (Heroku, Railway, etc.)

## API Endpoints

- `POST /upload`: Upload PDF or image files for text extraction
- `POST /create_event`: Create Google Calendar events from extracted text
- `GET /health`: Health check endpoint

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Google Calendar API for calendar integration
- Supabase for authentication and database
- Tesseract OCR for image text extraction
- PyMuPDF for PDF text extraction
