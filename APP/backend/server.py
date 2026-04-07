from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, Request
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
from emergentintegrations.llm.chat import LlmChat, UserMessage
from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionResponse, CheckoutStatusResponse, CheckoutSessionRequest
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import inch
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import asyncio
import resend

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'travelsmart-secret-key-2025')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION = 24  # hours

# Security
security = HTTPBearer()

# Platform Service Fee
SERVICE_FEE_PERCENT = 5.0  # 5% platform fee

# Resend Email Config
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'onboarding@resend.dev')
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

# Create the main app
app = FastAPI()
api_router = APIRouter(prefix="/api")

# ===== DESTINATION COST PER DAY (for budget-aware itinerary) =====
DESTINATION_COST_PER_DAY = {
    "malaysia": 8000,
    "kuala lumpur": 8000,
    "dubai": 12000,
    "goa": 4000,
    "singapore": 10000,
    "paris": 15000,
    "london": 14000,
    "tokyo": 13000,
    "bali": 6000,
    "maldives": 20000,
    "thailand": 5000,
    "bangkok": 5000,
    "new york": 16000,
    "sydney": 14000,
    "mumbai": 5000,
    "delhi": 4500,
    "jaipur": 4000,
    "kerala": 5000,
    "manali": 4500,
    "ladakh": 6000,
}

# ===== HEALTH CHECK ENDPOINT (for Kubernetes) =====
@app.get("/health")
async def health_check():
    """Health check endpoint for Kubernetes liveness/readiness probes"""
    return {"status": "healthy", "service": "travelsmart-backend"}

# ===== MODELS =====
class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    password_hash: str
    name: str
    role: str = "user"  # user or admin
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Destination(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    country: str
    city: str
    type: str  # flight, hotel, tour
    description: str
    price: int  # in INR
    duration: str
    rating: float
    image: str
    lat: float
    lng: float

class Booking(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    destination_id: str
    destination_name: str
    user_name: str
    user_email: str
    travelers: int
    travel_date: str
    amount: int  # in INR
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class BookingCreate(BaseModel):
    destination_id: str
    travelers: int
    travel_date: str

class Payment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    booking_id: str
    transaction_id: str
    amount: int
    status: str = "success"
    payment_method: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class PaymentCreate(BaseModel):
    booking_id: str
    payment_method: str

class ChatMessage(BaseModel):
    user_id: str
    message: str

class TripPlan(BaseModel):
    destination: str
    days: int
    interests: str

# ===== NEW MODELS FOR EXTENDED FEATURES =====
class ChatHistory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    user_message: str
    bot_response: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class FlightSearch(BaseModel):
    source: str
    destination: str
    date: str
    passengers: int = 1

class BookingCreate(BaseModel):
    item_type: str  # flight, hotel, tour
    item_id: str
    travelers: int
    travel_date: str
    details: dict

class BookingModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    user_email: str
    item_type: str
    item_id: str
    item_name: str
    travelers: int
    travel_date: str
    amount: int
    status: str = "Confirmed (Payment Pending)"
    details: dict
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# ===== NEW MODELS FOR EXTENDED FEATURES (Phase 2) =====

class UserBehavior(BaseModel):
    """Track user behavior for AI learning"""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    action_type: str  # search, view, book, chat
    destination_id: Optional[str] = None
    destination_name: Optional[str] = None
    search_query: Optional[str] = None
    budget_range: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ItineraryRequest(BaseModel):
    destination: str
    days: int
    travel_date: str
    interests: str
    budget: Optional[int] = None

class Itinerary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    destination: str
    days: int
    travel_date: str
    interests: str
    budget: Optional[int] = None
    content: str  # Generated itinerary text
    pdf_path: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class EmailLog(BaseModel):
    """Mock email log for simulated notifications"""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    user_email: str
    email_type: str  # booking_confirmation, itinerary_generated
    subject: str
    body: str
    status: str = "sent"  # simulated
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ===== HELPER FUNCTIONS =====
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_token(user_id: str, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid authentication")
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication")


async def get_admin_user(current_user: dict = Depends(get_current_user)):
    """Verify user is admin"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ===== LANGUAGE DETECTION HELPER =====
def detect_language(text: str) -> str:
    """Simple language detection based on script/keywords"""
    # Hindi Unicode range: \u0900-\u097F (Devanagari)
    # Marathi also uses Devanagari script
    
    hindi_chars = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    
    # Common Hindi words
    hindi_keywords = ['कैसे', 'क्या', 'कहाँ', 'कब', 'कौन', 'मुझे', 'मैं', 'है', 'हैं', 'और', 'में', 'को', 'से', 'पर', 'का', 'की', 'के', 'यात्रा', 'होटल', 'फ्लाइट']
    # Common Marathi words
    marathi_keywords = ['कसे', 'काय', 'कुठे', 'केव्हा', 'कोण', 'मला', 'मी', 'आहे', 'आहेत', 'आणि', 'मध्ये', 'ला', 'पासून', 'वर', 'चा', 'ची', 'चे', 'प्रवास', 'हॉटेल']
    
    text_lower = text.lower()
    
    if hindi_chars > len(text) * 0.2:  # More than 20% Devanagari
        # Check for Marathi-specific words
        marathi_count = sum(1 for word in marathi_keywords if word in text)
        hindi_count = sum(1 for word in hindi_keywords if word in text)
        
        if marathi_count > hindi_count:
            return "marathi"
        return "hindi"
    
    return "english"


# ===== EMAIL SERVICE (Resend + Fallback) =====
def build_email_html(subject: str, body: str) -> str:
    """Build HTML email template"""
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #f8fafc; padding: 20px;">
        <div style="background: #1e40af; color: white; padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
            <h1 style="margin: 0; font-size: 24px;">TravelSmart</h1>
            <p style="margin: 5px 0 0; opacity: 0.8; font-size: 14px;">AI-Powered Travel Booking</p>
        </div>
        <div style="background: white; padding: 24px; border-radius: 0 0 8px 8px; border: 1px solid #e2e8f0;">
            <h2 style="color: #1e293b; margin-top: 0;">{subject}</h2>
            <div style="color: #475569; line-height: 1.6; white-space: pre-line;">{body}</div>
        </div>
        <div style="text-align: center; padding: 16px; color: #94a3b8; font-size: 12px;">
            <p>TravelSmart - Your trusted travel companion</p>
        </div>
    </div>
    """

async def send_email(user_id: str, user_email: str, email_type: str, subject: str, body: str):
    """Send email via Resend (with fallback to mock logging)"""
    email_log = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "user_email": user_email,
        "email_type": email_type,
        "subject": subject,
        "body": body,
        "status": "pending",
        "delivery_method": "resend" if RESEND_API_KEY else "mock",
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    if RESEND_API_KEY:
        try:
            html_content = build_email_html(subject, body)
            params = {
                "from": SENDER_EMAIL,
                "to": [user_email],
                "subject": f"TravelSmart - {subject}",
                "html": html_content
            }
            result = await asyncio.to_thread(resend.Emails.send, params)
            email_log["status"] = "delivered"
            email_log["resend_id"] = result.get("id") if isinstance(result, dict) else str(result)
            logging.info(f"Email sent via Resend to {user_email}: {subject}")
        except Exception as e:
            logging.error(f"Resend email failed: {str(e)}, falling back to mock")
            email_log["status"] = "mock_fallback"
            email_log["error"] = str(e)
    else:
        email_log["status"] = "mock"
        logging.info(f"[MOCK EMAIL] To: {user_email} | Subject: {subject}")

    await db.email_logs.insert_one(email_log)
    return email_log

# Keep backward compatibility alias
send_mock_email = send_email


# ===== USER BEHAVIOR TRACKING =====
async def track_user_behavior(user_id: str, action_type: str, **kwargs):
    """Track user behavior for AI learning"""
    behavior = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "action_type": action_type,
        "destination_id": kwargs.get("destination_id"),
        "destination_name": kwargs.get("destination_name"),
        "search_query": kwargs.get("search_query"),
        "budget_range": kwargs.get("budget_range"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    await db.user_behavior.insert_one(behavior)
    return behavior


# ===== ITINERARY PDF GENERATOR =====
def generate_itinerary_pdf(itinerary: dict, user: dict) -> str:
    """Generate PDF itinerary"""
    itineraries_dir = ROOT_DIR / "itineraries"
    itineraries_dir.mkdir(exist_ok=True)
    
    filename = f"itinerary_{itinerary['id']}.pdf"
    filepath = itineraries_dir / filename
    
    doc = SimpleDocTemplate(str(filepath), pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    
    # Title style
    title_style = ParagraphStyle(
        'ItineraryTitle',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=colors.HexColor('#2563eb'),
        spaceAfter=20,
        alignment=1  # Center
    )
    
    # Subtitle style
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=14,
        textColor=colors.grey,
        spaceAfter=30,
        alignment=1
    )
    
    # Section header style
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#1e40af'),
        spaceBefore=20,
        spaceAfter=10
    )
    
    # Title
    story.append(Paragraph("✈️ TravelSmart Itinerary", title_style))
    story.append(Paragraph(f"Your personalized travel plan to {itinerary['destination']}", subtitle_style))
    story.append(Spacer(1, 0.3*inch))
    
    # Trip details table
    story.append(Paragraph("📋 Trip Details", section_style))
    trip_data = [
        ['Destination', itinerary['destination']],
        ['Duration', f"{itinerary['days']} Days"],
        ['Travel Date', itinerary['travel_date']],
        ['Interests', itinerary['interests']],
        ['Traveler', user['name']],
        ['Email', user['email']]
    ]
    
    if itinerary.get('budget'):
        trip_data.append(['Budget', f"₹{itinerary['budget']:,}"])
    
    table = Table(trip_data, colWidths=[2*inch, 4*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#eff6ff')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey)
    ]))
    story.append(table)
    story.append(Spacer(1, 0.4*inch))
    
    # Itinerary content
    story.append(Paragraph("🗓️ Day-wise Itinerary", section_style))
    
    # Parse and format the itinerary content
    content_lines = itinerary['content'].split('\n')
    for line in content_lines:
        if line.strip():
            # Check if it's a day header
            if line.strip().startswith('Day') or line.strip().startswith('**Day'):
                clean_line = line.replace('**', '').strip()
                story.append(Paragraph(f"<b>{clean_line}</b>", styles['Normal']))
            else:
                clean_line = line.replace('**', '').replace('*', '•').strip()
                story.append(Paragraph(clean_line, styles['Normal']))
            story.append(Spacer(1, 0.1*inch))
    
    story.append(Spacer(1, 0.5*inch))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.grey,
        alignment=1
    )
    story.append(Paragraph(f"Generated on: {datetime.now(timezone.utc).strftime('%B %d, %Y')}", footer_style))
    story.append(Paragraph("Thank you for choosing TravelSmart!", footer_style))
    story.append(Paragraph("🌍 Safe travels!", footer_style))
    
    doc.build(story)
    return str(filepath)


def generate_invoice_pdf(booking: dict, payment: dict, user: dict) -> str:
    """Generate PDF invoice"""
    invoices_dir = ROOT_DIR / "invoices"
    invoices_dir.mkdir(exist_ok=True)
    
    filename = f"invoice_{booking['id']}.pdf"
    filepath = invoices_dir / filename
    
    doc = SimpleDocTemplate(str(filepath), pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2563eb'),
        spaceAfter=30,
    )
    story.append(Paragraph("TravelSmart", title_style))
    story.append(Spacer(1, 0.2*inch))
    
    # Invoice header
    story.append(Paragraph(f"<b>Invoice ID:</b> {booking['id'][:8].upper()}", styles['Normal']))
    story.append(Paragraph(f"<b>Date:</b> {datetime.now(timezone.utc).strftime('%B %d, %Y')}", styles['Normal']))
    story.append(Spacer(1, 0.3*inch))
    
    # Customer details
    story.append(Paragraph("<b>Customer Details</b>", styles['Heading2']))
    story.append(Paragraph(f"Name: {user['name']}", styles['Normal']))
    story.append(Paragraph(f"Email: {user['email']}", styles['Normal']))
    story.append(Spacer(1, 0.3*inch))
    
    # Booking details
    story.append(Paragraph("<b>Booking Details</b>", styles['Heading2']))
    base_amt = booking.get('base_amount', booking.get('amount', 0))
    fee = booking.get('service_fee', 0)
    total = booking.get('amount', base_amt)
    data = [
        ['Description', 'Details'],
        ['Destination', booking.get('destination_name', booking.get('item_name', 'N/A'))],
        ['Travelers', str(booking.get('travelers', 1))],
        ['Travel Date', booking.get('travel_date', 'N/A')],
        ['Base Amount', f"INR {base_amt:,}"],
        ['Service Fee (5%)', f"INR {fee:,}"],
        ['Total Amount', f"INR {total:,}"],
        ['Transaction ID', payment.get('transaction_id', 'N/A')],
        ['Status', 'PAID']
    ]
    
    table = Table(data, colWidths=[2*inch, 4*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(table)
    story.append(Spacer(1, 0.5*inch))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.grey,
        alignment=1  # Center
    )
    story.append(Paragraph("Thank you for booking with TravelSmart", footer_style))
    story.append(Paragraph("Developed by Simran Godhwani – TravelSmart 2025", footer_style))
    
    doc.build(story)
    return str(filepath)

# ===== AUTH ROUTES =====
@api_router.post("/auth/signup")
async def signup(user_data: UserCreate):
    # Check if user exists
    existing = await db.users.find_one({"email": user_data.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    user = User(
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        name=user_data.name
    )
    
    doc = user.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.users.insert_one(doc)
    
    # Create token
    token = create_token(user.id, user.email)
    
    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name
        }
    }

@api_router.post("/auth/login")
async def login(credentials: UserLogin):
    # Find user
    user = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    if not verify_password(credentials.password, user['password_hash']):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create token
    token = create_token(user['id'], user['email'])
    
    return {
        "token": token,
        "user": {
            "id": user['id'],
            "email": user['email'],
            "name": user['name']
        }
    }

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user['id'],
        "email": current_user['email'],
        "name": current_user['name']
    }

# ===== DESTINATIONS ROUTES =====
@api_router.get("/destinations")
async def get_destinations():
    destinations = await db.destinations.find({}, {"_id": 0}).to_list(100)
    return destinations

@api_router.get("/destinations/{destination_id}")
async def get_destination(destination_id: str):
    destination = await db.destinations.find_one({"id": destination_id}, {"_id": 0})
    if not destination:
        raise HTTPException(status_code=404, detail="Destination not found")
    return destination

# ===== BOOKINGS ROUTES =====
@api_router.post("/bookings")
async def create_booking(booking_data: BookingCreate, current_user: dict = Depends(get_current_user)):
    # Get destination
    destination = await db.destinations.find_one({"id": booking_data.destination_id}, {"_id": 0})
    if not destination:
        raise HTTPException(status_code=404, detail="Destination not found")
    
    # Calculate amount
    amount = destination['price'] * booking_data.travelers
    
    # Create booking
    booking = Booking(
        user_id=current_user['id'],
        destination_id=destination['id'],
        destination_name=destination['name'],
        user_name=current_user['name'],
        user_email=current_user['email'],
        travelers=booking_data.travelers,
        travel_date=booking_data.travel_date,
        amount=amount,
        status="pending"
    )
    
    doc = booking.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.bookings.insert_one(doc)
    
    return booking

@api_router.get("/bookings/my")
async def get_my_bookings(current_user: dict = Depends(get_current_user)):
    """Get user's bookings"""
    try:
        bookings = await db.bookings.find(
            {"user_id": current_user['id']},
            {"_id": 0}
        ).sort("created_at", -1).to_list(100)
        return {"bookings": bookings, "count": len(bookings)}
    except Exception as e:
        logging.error(f"Get bookings error: {str(e)}")
        return {"bookings": [], "count": 0}

@api_router.get("/bookings")
async def get_user_bookings(current_user: dict = Depends(get_current_user)):
    bookings = await db.bookings.find({"user_id": current_user['id']}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return bookings

@api_router.get("/bookings/{booking_id}")
async def get_booking(booking_id: str, current_user: dict = Depends(get_current_user)):
    booking = await db.bookings.find_one({"id": booking_id, "user_id": current_user['id']}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking

# ===== PAYMENTS ROUTES =====
@api_router.post("/payments/create")
async def create_payment(payment_data: PaymentCreate, current_user: dict = Depends(get_current_user)):
    # Get booking
    booking = await db.bookings.find_one({"id": payment_data.booking_id, "user_id": current_user['id']}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Create payment
    transaction_id = f"TXN-{str(uuid.uuid4())[:8].upper()}"
    payment = Payment(
        booking_id=booking['id'],
        transaction_id=transaction_id,
        amount=booking['amount'],
        status="success",
        payment_method=payment_data.payment_method
    )
    
    doc = payment.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.payments.insert_one(doc)
    
    # Update booking status
    await db.bookings.update_one(
        {"id": booking['id']},
        {"$set": {"status": "confirmed"}}
    )
    
    # Generate invoice
    user = await db.users.find_one({"id": current_user['id']}, {"_id": 0})
    booking['status'] = 'confirmed'
    invoice_path = generate_invoice_pdf(booking, doc, user)
    
    return {
        "payment": payment,
        "transaction_id": transaction_id,
        "status": "success"
    }

@api_router.get("/payments/{booking_id}")
async def get_payment(booking_id: str, current_user: dict = Depends(get_current_user)):
    payment = await db.payments.find_one({"booking_id": booking_id}, {"_id": 0})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment

# ===== INVOICE ROUTES =====
@api_router.get("/invoice/{booking_id}")
async def download_invoice(booking_id: str, current_user: dict = Depends(get_current_user)):
    # Verify booking belongs to user
    booking = await db.bookings.find_one({"id": booking_id, "user_id": current_user['id']}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    invoice_path = ROOT_DIR / "invoices" / f"invoice_{booking_id}.pdf"
    if not invoice_path.exists():
        # Try payment_transactions first (Stripe), then legacy payments
        payment = await db.payment_transactions.find_one({"booking_id": booking_id, "payment_status": "paid"}, {"_id": 0})
        if payment:
            payment_doc = {
                "transaction_id": f"STR-{payment.get('session_id', 'N/A')[:8].upper()}",
                "amount": payment.get('amount', booking.get('amount', 0)),
                "status": "success",
                "payment_method": "stripe"
            }
        else:
            payment_doc = await db.payments.find_one({"booking_id": booking_id}, {"_id": 0})
            if not payment_doc:
                payment_doc = {"transaction_id": booking_id[:8].upper(), "amount": booking.get('amount', 0), "status": "paid", "payment_method": "N/A"}
        user = await db.users.find_one({"id": current_user['id']}, {"_id": 0})
        generate_invoice_pdf(booking, payment_doc, user)
    
    return FileResponse(
        path=str(invoice_path),
        media_type='application/pdf',
        filename=f"TravelSmart_Invoice_{booking_id[:8]}.pdf"
    )

# ===== AI ROUTES =====
@api_router.post("/ai/chat")
async def ai_chat(message: ChatMessage, current_user: dict = Depends(get_current_user)):
    try:
        api_key = os.environ.get('EMERGENT_LLM_KEY')
        
        # Detect language from user message
        detected_lang = detect_language(message.message)
        
        # Get relevant destination data to provide context
        destinations = await db.destinations.find({}, {"_id": 0}).to_list(100)
        
        # Get user behavior for personalized recommendations
        user_behaviors = await db.user_behavior.find(
            {"user_id": current_user['id']},
            {"_id": 0}
        ).sort("timestamp", -1).limit(20).to_list(20)
        
        # Extract patterns from behavior
        searched_destinations = [b.get('destination_name') for b in user_behaviors if b.get('destination_name')]
        search_queries = [b.get('search_query') for b in user_behaviors if b.get('search_query')]
        
        behavior_context = ""
        if searched_destinations or search_queries:
            behavior_context = f"""
User Preferences (based on past behavior):
- Recently viewed: {', '.join(searched_destinations[:5]) if searched_destinations else 'None'}
- Recent searches: {', '.join(search_queries[:5]) if search_queries else 'None'}
Use this to provide personalized recommendations.
"""
        
        # Create context about available destinations
        context = f"""You have access to TravelSmart's destination database. Here's what's available:

Total Packages: {len(destinations)}
- Flights: {sum(1 for d in destinations if d.get('type') == 'flight')} packages
- Hotels: {sum(1 for d in destinations if d.get('type') == 'hotel')} packages  
- Tours: {sum(1 for d in destinations if d.get('type') == 'tour')} packages

Price Range: ₹{min(d.get('price', 0) for d in destinations):,} - ₹{max(d.get('price', 0) for d in destinations):,}

Popular Destinations: {', '.join([d.get('city', '') for d in destinations[:10]])}

{behavior_context}

When users ask about specific requirements (budget, destination type, etc.), search through this data and provide specific recommendations with names and prices."""
        
        # Language-specific system message
        lang_instruction = ""
        if detected_lang == "hindi":
            lang_instruction = """
IMPORTANT: The user is writing in Hindi. You MUST respond in Hindi (हिंदी में जवाब दें).
Use Devanagari script for your response. Be natural and conversational in Hindi."""
        elif detected_lang == "marathi":
            lang_instruction = """
IMPORTANT: The user is writing in Marathi. You MUST respond in Marathi (मराठी मध्ये उत्तर द्या).
Use Devanagari script for your response. Be natural and conversational in Marathi."""
        else:
            lang_instruction = "Respond in English."
        
        system_message = f"""You are TravelSmart's AI travel assistant. Help users find their perfect trip.

{lang_instruction}

{context}

Guidelines:
- Be friendly and conversational
- When users ask about budget (e.g., "under ₹10,000"), suggest actual packages in that range
- For destination queries, recommend specific places from our catalog
- Provide prices in ₹ (INR) format
- Keep responses concise (2-3 sentences max)
- Always be helpful and encouraging
- You can help with itineraries, recommendations, flights, weather, and bookings"""
        
        chat = LlmChat(
            api_key=api_key,
            session_id=f"chat_{current_user['id']}",
            system_message=system_message
        ).with_model("openai", "gpt-4o-mini")
        
        user_message = UserMessage(text=message.message)
        response = await chat.send_message(user_message)
        
        # Save chat to history with language
        chat_entry = {
            "id": str(uuid.uuid4()),
            "user_id": current_user['id'],
            "user_message": message.message,
            "bot_response": response,
            "language": detected_lang,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await db.chat_history.insert_one(chat_entry)
        
        # Track behavior
        await track_user_behavior(
            current_user['id'],
            "chat",
            search_query=message.message
        )
        
        return {"response": response, "hasData": True, "language": detected_lang}
    except Exception as e:
        logging.error(f"AI chat error: {str(e)}")
        raise HTTPException(status_code=500, detail="AI service error")

@api_router.post("/ai/recommendations")
async def ai_recommendations(current_user: dict = Depends(get_current_user)):
    try:
        api_key = os.environ.get('EMERGENT_LLM_KEY')
        
        # Get user's booking history
        bookings = await db.bookings.find({"user_id": current_user['id']}, {"_id": 0}).limit(5).to_list(5)
        booking_history = ", ".join([b.get('destination_name', b.get('item_name', 'Unknown')) for b in bookings]) if bookings else "No previous bookings"
        
        chat = LlmChat(
            api_key=api_key,
            session_id=f"rec_{current_user['id']}",
            system_message="You are a travel recommendation expert. Suggest 3-4 destinations based on user history."
        ).with_model("openai", "gpt-4o-mini")
        
        prompt = f"User's previous bookings: {booking_history}. Suggest 3-4 new travel destinations with brief reasons (2-3 sentences each). Format as bullet points."
        user_message = UserMessage(text=prompt)
        response = await chat.send_message(user_message)
        
        return {"recommendations": response}
    except Exception as e:
        logging.error(f"AI recommendations error: {str(e)}")
        raise HTTPException(status_code=500, detail="AI service error")

@api_router.post("/ai/plan-trip")
async def plan_trip(trip_data: TripPlan, current_user: dict = Depends(get_current_user)):
    try:
        api_key = os.environ.get('EMERGENT_LLM_KEY')
        
        chat = LlmChat(
            api_key=api_key,
            session_id=f"plan_{current_user['id']}",
            system_message="You are a professional trip planner. Create detailed day-by-day itineraries."
        ).with_model("openai", "gpt-4o-mini")
        
        prompt = f"Create a detailed {trip_data.days}-day itinerary for {trip_data.destination}. Interests: {trip_data.interests}. Include daily activities, best times to visit, and local tips. Format with Day 1, Day 2, etc."
        user_message = UserMessage(text=prompt)
        response = await chat.send_message(user_message)
        
        return {"itinerary": response}
    except Exception as e:
        logging.error(f"Trip planning error: {str(e)}")
        raise HTTPException(status_code=500, detail="AI service error")


# ===== SMART SEARCH FOR CHATBOT =====
@api_router.get("/ai/search-destinations")
async def search_destinations(
    budget: Optional[int] = None,
    destination_type: Optional[str] = None,
    max_results: int = 5,
    current_user: dict = Depends(get_current_user)
):
    """Search destinations based on criteria for chatbot"""
    try:
        query = {}
        
        # Filter by budget
        if budget:
            query["price"] = {"$lte": budget}
        
        # Filter by type
        if destination_type and destination_type in ["flight", "hotel", "tour"]:
            query["type"] = destination_type
        
        # Get matching destinations
        destinations = await db.destinations.find(
            query, 
            {"_id": 0}
        ).sort("price", 1).limit(max_results).to_list(max_results)
        
        return {
            "results": destinations,
            "count": len(destinations),
            "criteria": {"budget": budget, "type": destination_type}
        }
    except Exception as e:
        logging.error(f"Search error: {str(e)}")
        raise HTTPException(status_code=500, detail="Search failed")



# ===== CHAT HISTORY ENDPOINTS =====
@api_router.get("/chat/history")
async def get_chat_history(current_user: dict = Depends(get_current_user)):
    """Get user's chat history"""
    try:
        history = await db.chat_history.find(
            {"user_id": current_user['id']},
            {"_id": 0}
        ).sort("timestamp", -1).limit(50).to_list(50)
        return {"history": history, "count": len(history)}
    except Exception as e:
        logging.error(f"Chat history error: {str(e)}")
        return {"history": [], "count": 0}

@api_router.post("/chat/save")
async def save_chat(user_message: str, bot_response: str, current_user: dict = Depends(get_current_user)):
    """Save chat interaction"""
    try:
        chat_entry = {
            "id": str(uuid.uuid4()),
            "user_id": current_user['id'],
            "user_message": user_message,
            "bot_response": bot_response,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await db.chat_history.insert_one(chat_entry)
        return {"success": True}
    except Exception as e:
        logging.error(f"Save chat error: {str(e)}")
        return {"success": False}

@api_router.delete("/chat/history")
async def clear_chat_history(current_user: dict = Depends(get_current_user)):
    """Clear user's chat history"""
    try:
        result = await db.chat_history.delete_many({"user_id": current_user['id']})
        return {"success": True, "deleted": result.deleted_count}
    except Exception as e:
        logging.error(f"Clear chat error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to clear history")

# ===== FLIGHT SEARCH ENDPOINTS =====
@api_router.post("/flights/search")
async def search_flights(search: FlightSearch, current_user: dict = Depends(get_current_user)):
    """Search flights with mock data - with pre-booking buffer filtering"""
    try:
        import random
        from datetime import datetime, timedelta
        
        airlines = ["Air India", "IndiGo", "SpiceJet", "Vistara", "Air Asia"]
        base_price = random.randint(3000, 15000)
        
        # Parse search date
        search_date = datetime.strptime(search.date, "%Y-%m-%d").date()
        today = datetime.now().date()
        current_time = datetime.now()
        
        flights = []
        for i in range(5):  # Generate 5 potential flights
            # Generate departure time
            hour = random.randint(6, 22)
            minute = random.choice([0, 15, 30, 45])
            departure_time_str = f"{hour:02d}:{minute:02d}"
            
            # Calculate arrival time (1-8 hours later)
            duration_hours = random.randint(1, 8)
            duration_minutes = random.randint(0, 59)
            arrival_hour = (hour + duration_hours) % 24
            arrival_minute = (minute + duration_minutes) % 60
            
            flight = {
                "flight_id": f"FL{random.randint(1000, 9999)}",
                "airline": random.choice(airlines),
                "source": search.source,
                "destination": search.destination,
                "date": search.date,
                "departure_time": departure_time_str,
                "arrival_time": f"{arrival_hour:02d}:{arrival_minute:02d}",
                "duration": f"{duration_hours}h {duration_minutes}m",
                "price": base_price + (i * 1500),
                "seats_available": random.randint(5, 45),
                "class": "Economy"
            }
            
            # Apply pre-booking buffer filter for today's date
            if search_date == today:
                # Parse departure time
                flight_departure = datetime.combine(today, datetime.strptime(departure_time_str, "%H:%M").time())
                time_until_departure = (flight_departure - current_time).total_seconds() / 3600  # hours
                
                # Only include flights with more than 2 hours buffer
                if time_until_departure >= 2:
                    flights.append(flight)
            else:
                # Future dates: include all flights
                flights.append(flight)
        
        # If all flights filtered out, return message
        if not flights and search_date == today:
            return {
                "flights": [],
                "count": 0,
                "source": "mock",
                "message": "No flights available due to minimum pre-booking buffer policy. Please select a future date.",
                "buffer_applied": True
            }
        
        return {"flights": flights, "count": len(flights), "source": "mock", "buffer_applied": search_date == today}
    except Exception as e:
        logging.error(f"Flight search error: {str(e)}")
        raise HTTPException(status_code=500, detail="Flight search failed")

# ===== WEATHER API ENDPOINT =====
@api_router.get("/weather/{city}")
async def get_weather(city: str):
    """Get weather for city (mock data for demo)"""
    try:
        import random
        
        # Mock weather data
        conditions = ["Sunny", "Partly Cloudy", "Cloudy", "Rainy", "Clear"]
        weather = {
            "city": city,
            "temperature": random.randint(15, 35),
            "condition": random.choice(conditions),
            "humidity": random.randint(40, 90),
            "wind_speed": random.randint(5, 25),
            "forecast": "Pleasant weather expected"
        }
        
        return weather
    except Exception as e:
        logging.error(f"Weather error: {str(e)}")
        return {
            "city": city,
            "temperature": 25,
            "condition": "Pleasant",
            "humidity": 60,
            "wind_speed": 10,
            "forecast": "Data unavailable"
        }


# ===== WEATHER WARNING ENDPOINT =====
@api_router.get("/weather-warning/{destination}")
async def get_weather_warning(destination: str):
    """Get weather warning for travel advisory - uses OpenWeatherMap API with fallback"""
    try:
        import httpx
        import random
        
        weather_api_key = os.environ.get('WEATHER_API_KEY')
        temperature = None
        condition = None
        humidity = 60
        
        # Try OpenWeatherMap API if key is available
        if weather_api_key:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"https://api.openweathermap.org/data/2.5/weather",
                        params={
                            "q": destination,
                            "appid": weather_api_key,
                            "units": "metric"
                        },
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        data = response.json()
                        temperature = round(data.get("main", {}).get("temp", 25))
                        humidity = data.get("main", {}).get("humidity", 60)
                        weather_data = data.get("weather", [{}])[0]
                        condition = weather_data.get("description", "").title()
                        logging.info(f"Weather API success for {destination}: {temperature}°C, {condition}")
            except Exception as api_error:
                logging.warning(f"Weather API failed for {destination}: {str(api_error)}")
        
        # Fallback to realistic mock data if API unavailable
        if temperature is None:
            # Use consistent mock data based on destination name
            dest_hash = sum(ord(c) for c in destination.lower())
            random.seed(dest_hash + datetime.now().day)  # Consistent for same day
            
            conditions = ["Sunny", "Partly Cloudy", "Cloudy", "Light Rain", "Heavy Rain", "Thunderstorm", "Clear", "Hazy"]
            condition = conditions[dest_hash % len(conditions)]
            temperature = 20 + (dest_hash % 20)  # 20-40°C range
            humidity = 40 + (dest_hash % 50)
            random.seed()  # Reset seed
        
        # Determine risk level based on conditions
        high_risk_conditions = ["thunderstorm", "storm", "heavy rain", "tornado", "hurricane"]
        condition_lower = condition.lower() if condition else ""
        
        if any(risk in condition_lower for risk in high_risk_conditions):
            risk_level = "high"
            message = f"⚠️ Severe weather warning: {condition} expected in {destination}. Outdoor travel may be affected."
        elif temperature and temperature > 38:
            risk_level = "moderate"
            message = f"🌡️ High temperature warning: {temperature}°C in {destination}. Travel precautions advised."
        else:
            risk_level = "safe"
            message = f"✅ Weather conditions look suitable for travel to {destination}."
        
        # Generate packing suggestions based on weather
        packing_suggestions = generate_packing_suggestions(temperature, condition_lower)
        
        return {
            "destination": destination,
            "temperature": temperature,
            "condition": condition,
            "risk_level": risk_level,
            "message": message,
            "humidity": humidity,
            "advisory": "Check local weather updates before travel",
            "packing_suggestions": packing_suggestions,
            "api_source": "openweathermap" if weather_api_key else "mock"
        }
    except Exception as e:
        logging.error(f"Weather warning error: {str(e)}")
        return {
            "destination": destination,
            "temperature": None,
            "condition": "Unknown",
            "risk_level": "unknown",
            "message": "Weather information currently unavailable.",
            "humidity": None,
            "packing_suggestions": [],
            "api_source": "error"
        }


def generate_packing_suggestions(temperature: int, condition: str) -> list:
    """Generate smart packing suggestions based on weather"""
    suggestions = []
    condition = condition.lower() if condition else ""
    
    # Rain-related items
    if any(word in condition for word in ["rain", "drizzle", "shower", "storm", "thunderstorm"]):
        suggestions.extend([
            "☔ Umbrella",
            "🧥 Light raincoat or waterproof jacket",
            "👟 Water-resistant footwear"
        ])
    
    # Hot weather items
    if temperature and temperature > 32:
        suggestions.extend([
            "🧴 Sunscreen (SPF 30+)",
            "🧢 Hat or cap",
            "👕 Light, breathable clothing",
            "💧 Reusable water bottle",
            "🕶️ Sunglasses"
        ])
    elif temperature and temperature > 25:
        suggestions.extend([
            "🧴 Sunscreen",
            "👕 Light clothing",
            "🕶️ Sunglasses"
        ])
    
    # Cold weather items
    if temperature and temperature < 15:
        suggestions.extend([
            "🧥 Warm jacket or coat",
            "🧣 Scarf",
            "🧤 Gloves",
            "👖 Warm clothing layers"
        ])
    elif temperature and temperature < 22:
        suggestions.extend([
            "🧥 Light jacket",
            "👕 Layered clothing"
        ])
    
    # General items always useful
    if not suggestions:
        suggestions = [
            "👕 Comfortable clothing",
            "🧴 Basic toiletries",
            "📱 Phone charger"
        ]
    
    return suggestions


# ===== TRAVEL RISK INDEX ENDPOINT =====
@api_router.get("/travel-risk/{destination}")
async def get_travel_risk_index(
    destination: str,
    budget: Optional[int] = None
):
    """Calculate Travel Risk Index score (0-100) based on weather, budget, and destination cost"""
    try:
        # Start with perfect score
        risk_score = 100
        risk_factors = []
        
        # Get weather data
        weather_data = await get_weather_warning(destination)
        weather_risk = weather_data.get("risk_level", "safe")
        
        # Deduct for weather risk
        if weather_risk == "moderate":
            risk_score -= 20
            risk_factors.append("Moderate weather conditions (-20)")
        elif weather_risk == "high":
            risk_score -= 40
            risk_factors.append("Severe weather warning (-40)")
        
        # Get destination cost
        dest_lower = destination.lower()
        avg_daily_cost = DESTINATION_COST_PER_DAY.get(dest_lower, 6000)
        
        # Deduct for budget feasibility
        if budget:
            if budget < avg_daily_cost:
                risk_score -= 30
                risk_factors.append(f"Budget below daily cost estimate (-30)")
            elif budget < avg_daily_cost * 1.5:
                risk_score -= 10
                risk_factors.append("Tight budget margin (-10)")
        
        # Ensure minimum score of 10
        risk_score = max(10, risk_score)
        
        # Determine risk category
        if risk_score >= 80:
            category = "Low Risk"
            recommendation = "Great conditions for travel!"
        elif risk_score >= 60:
            category = "Moderate Risk"
            recommendation = "Proceed with some caution."
        elif risk_score >= 40:
            category = "Elevated Risk"
            recommendation = "Consider reviewing your travel plans."
        else:
            category = "High Risk"
            recommendation = "Significant concerns exist. Review carefully."
        
        return {
            "destination": destination,
            "risk_score": risk_score,
            "max_score": 100,
            "category": category,
            "recommendation": recommendation,
            "risk_factors": risk_factors,
            "weather_risk": weather_risk,
            "avg_daily_cost": avg_daily_cost,
            "budget_provided": budget,
            "packing_suggestions": weather_data.get("packing_suggestions", [])
        }
    except Exception as e:
        logging.error(f"Travel risk calculation error: {str(e)}")
        return {
            "destination": destination,
            "risk_score": 70,
            "max_score": 100,
            "category": "Unknown",
            "recommendation": "Unable to fully assess risk. Proceed with caution.",
            "risk_factors": ["Incomplete data"],
            "packing_suggestions": []
        }

# ===== BOOKING WORKFLOW ENDPOINTS =====
@api_router.post("/bookings/create")
async def create_booking_new(booking_data: BookingCreate, current_user: dict = Depends(get_current_user)):
    """Create booking without payment - with hotel inventory management and pre-booking buffer"""
    try:
        # Get item details
        item = await db.destinations.find_one({"id": booking_data.item_id}, {"_id": 0})
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        # ===== PRE-BOOKING BUFFER VALIDATION =====
        travel_date = datetime.strptime(booking_data.travel_date, "%Y-%m-%d")
        current_time = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # For flights: minimum 2 hours before departure
        if item.get('type') == 'flight':
            # Assume departure at 10:00 AM on travel date
            departure_time = travel_date.replace(hour=10, minute=0)
            time_until_departure = (departure_time - current_time).total_seconds() / 3600  # hours
            
            if time_until_departure < 2:
                raise HTTPException(
                    status_code=400,
                    detail="Booking not allowed due to minimum pre-booking buffer policy. Flight bookings require at least 2 hours before departure."
                )
        
        # For hotels: check-in time must not have passed
        if item.get('type') == 'hotel':
            # Assume check-in at 2:00 PM on travel date
            checkin_time = travel_date.replace(hour=14, minute=0)
            if current_time > checkin_time:
                raise HTTPException(
                    status_code=400,
                    detail="Booking not allowed due to minimum pre-booking buffer policy. Hotel check-in time has already passed."
                )
        
        # For tours: must book at least 1 day in advance
        if item.get('type') == 'tour':
            days_until_tour = (travel_date - current_time).days
            if days_until_tour < 1:
                raise HTTPException(
                    status_code=400,
                    detail="Booking not allowed due to minimum pre-booking buffer policy. Tour bookings require at least 1 day advance notice."
                )
        
        # Check hotel inventory if it's a hotel booking
        if item.get('type') == 'hotel':
            available_rooms = item.get('available_rooms', 999)  # Default to unlimited if not set
            if available_rooms < booking_data.travelers:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Not enough rooms available. Only {available_rooms} rooms left."
                )
        
        # Calculate amount with service fee
        base_amount = item.get('price', 0) * booking_data.travelers
        service_fee = round(base_amount * SERVICE_FEE_PERCENT / 100)
        amount = base_amount + service_fee
        
        # Create booking
        booking = {
            "id": str(uuid.uuid4()),
            "user_id": current_user['id'],
            "user_email": current_user['email'],
            "user_name": current_user['name'],
            "item_type": booking_data.item_type,
            "item_id": booking_data.item_id,
            "item_name": item.get('name', 'Unknown'),
            "travelers": booking_data.travelers,
            "travel_date": booking_data.travel_date,
            "base_amount": base_amount,
            "service_fee": service_fee,
            "service_fee_percent": SERVICE_FEE_PERCENT,
            "amount": amount,
            "status": "Confirmed (Payment Pending)",
            "details": booking_data.details,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        result = await db.bookings.insert_one(booking.copy())
        
        # Update hotel inventory if it's a hotel
        if item.get('type') == 'hotel' and item.get('available_rooms') is not None:
            await db.destinations.update_one(
                {"id": booking_data.item_id},
                {"$inc": {"available_rooms": -booking_data.travelers}}
            )
        
        # Track user behavior
        await track_user_behavior(
            current_user['id'],
            "book",
            destination_id=booking_data.item_id,
            destination_name=item.get('name')
        )
        
        # Send mock email notification
        email_body = f"""
Dear {current_user['name']},

🎉 Your booking has been confirmed!

📋 BOOKING DETAILS
━━━━━━━━━━━━━━━━━━━━
Booking ID: {booking['id'][:8].upper()}
Destination: {item.get('name')}
Travel Date: {booking_data.travel_date}
Travelers: {booking_data.travelers}
Total Amount: ₹{amount:,}
Status: Confirmed (Payment Pending)

💳 Please complete the payment to finalize your booking.

Thank you for choosing TravelSmart!
Safe travels! ✈️

━━━━━━━━━━━━━━━━━━━━
This is a simulated email notification.
"""
        await send_mock_email(
            current_user['id'],
            current_user['email'],
            "booking_confirmation",
            f"✅ Booking Confirmed - {item.get('name')}",
            email_body
        )
        
        # Return booking without MongoDB _id
        return {"success": True, "booking": booking, "email_sent": True}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Booking error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Booking failed: {str(e)}")

@api_router.delete("/bookings/{booking_id}")
async def cancel_booking(booking_id: str, current_user: dict = Depends(get_current_user)):
    """Cancel a booking - with hotel inventory restoration"""
    try:
        # Get booking first
        booking = await db.bookings.find_one(
            {"id": booking_id, "user_id": current_user['id']},
            {"_id": 0}
        )
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        # Update status
        result = await db.bookings.update_one(
            {"id": booking_id, "user_id": current_user['id']},
            {"$set": {"status": "Cancelled"}}
        )
        
        # Restore hotel inventory if it was a hotel booking
        if booking.get('item_type') == 'hotel':
            item = await db.destinations.find_one({"id": booking['item_id']}, {"_id": 0})
            if item and item.get('available_rooms') is not None:
                await db.destinations.update_one(
                    {"id": booking['item_id']},
                    {"$inc": {"available_rooms": booking['travelers']}}
                )
        
        return {"success": True, "message": "Booking cancelled"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Cancel booking error: {str(e)}")
        raise HTTPException(status_code=500, detail="Cancellation failed")

# ===== ADMIN ANALYTICS ENDPOINTS =====
@api_router.get("/admin/analytics")
async def get_analytics(admin_user: dict = Depends(get_admin_user)):
    """Get admin analytics dashboard data"""
    try:
        # Get counts
        total_users = await db.users.count_documents({})
        total_bookings = await db.bookings.count_documents({})
        total_chats = await db.chat_history.count_documents({})
        total_itineraries = await db.itineraries.count_documents({})
        total_emails = await db.email_logs.count_documents({})
        
        # Popular destinations
        bookings = await db.bookings.find({}, {"item_name": 1, "_id": 0}).to_list(1000)
        dest_counts = {}
        for b in bookings:
            name = b.get('item_name', 'Unknown')
            dest_counts[name] = dest_counts.get(name, 0) + 1
        popular = sorted(dest_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Recent bookings by day (last 7 days)
        from datetime import timedelta
        today = datetime.now(timezone.utc)
        daily_bookings = []
        for i in range(7):
            day = today - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59)
            
            count = await db.bookings.count_documents({
                "created_at": {
                    "$gte": day_start.isoformat(),
                    "$lte": day_end.isoformat()
                }
            })
            daily_bookings.append({
                "date": day.strftime("%Y-%m-%d"),
                "count": count
            })
        
        return {
            "total_users": total_users,
            "total_bookings": total_bookings,
            "active_chats": total_chats,
            "total_itineraries": total_itineraries,
            "total_emails": total_emails,
            "popular_destinations": [{"name": name, "bookings": count} for name, count in popular],
            "daily_bookings": list(reversed(daily_bookings)),
            "flight_searches": 0  # Can be tracked separately if needed
        }
    except Exception as e:
        logging.error(f"Analytics error: {str(e)}")
        raise HTTPException(status_code=500, detail="Analytics failed")

@api_router.get("/admin/users")
async def get_all_users(admin_user: dict = Depends(get_admin_user)):
    """Get all users (admin only)"""
    try:
        users = await db.users.find(
            {},
            {"_id": 0, "password_hash": 0}
        ).to_list(1000)
        return {"users": users, "count": len(users)}
    except Exception as e:
        logging.error(f"Get users error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch users")


# ===== ITINERARY ENDPOINTS =====
@api_router.post("/itinerary/generate")
async def generate_itinerary(request: ItineraryRequest, current_user: dict = Depends(get_current_user)):
    """Generate and save itinerary with PDF - Budget-aware logic"""
    try:
        # ===== BUDGET VALIDATION =====
        if request.budget and request.budget < 2000:
            raise HTTPException(
                status_code=400,
                detail="Budget too low. Minimum budget required is ₹2,000 for a meaningful trip."
            )
        
        # ===== BUDGET-AWARE DAYS CALCULATION =====
        destination_lower = request.destination.lower()
        avg_cost_per_day = DESTINATION_COST_PER_DAY.get(destination_lower, 6000)
        
        if request.budget:
            # Calculate optimal days based on budget
            calculated_days = max(1, min(10, request.budget // avg_cost_per_day))
            # Use calculated days if user didn't specify, or if their choice exceeds budget
            if request.days > calculated_days:
                actual_days = calculated_days
            else:
                actual_days = request.days
        else:
            actual_days = request.days
            calculated_days = request.days
        
        api_key = os.environ.get('EMERGENT_LLM_KEY')
        
        chat = LlmChat(
            api_key=api_key,
            session_id=f"itinerary_{current_user['id']}_{str(uuid.uuid4())[:8]}",
            system_message="You are a professional travel planner. Create detailed, practical day-by-day itineraries with bullet points for activities."
        ).with_model("openai", "gpt-4o-mini")
        
        budget_info = f" within a budget of ₹{request.budget:,}" if request.budget else ""
        prompt = f"""Create a realistic {actual_days}-day travel itinerary for {request.destination}{budget_info}.

Travel Date: {request.travel_date}
Interests: {request.interests}
Daily Budget: ₹{avg_cost_per_day:,} approximately

Include for each day:
• Morning activities with timings
• Afternoon activities and lunch spots
• Evening activities and dinner recommendations
• Estimated costs for each activity
• Transportation tips

Use bullet points for clarity. Format clearly with **Day 1**, **Day 2**, etc.
Keep the itinerary practical and budget-conscious."""

        user_message = UserMessage(text=prompt)
        itinerary_content = await chat.send_message(user_message)
        
        # Create itinerary record
        itinerary = {
            "id": str(uuid.uuid4()),
            "user_id": current_user['id'],
            "destination": request.destination,
            "days": actual_days,
            "requested_days": request.days,
            "travel_date": request.travel_date,
            "interests": request.interests,
            "budget": request.budget,
            "daily_cost_estimate": avg_cost_per_day,
            "content": itinerary_content,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Generate PDF
        user = await db.users.find_one({"id": current_user['id']}, {"_id": 0})
        pdf_path = generate_itinerary_pdf(itinerary, user)
        itinerary["pdf_path"] = pdf_path
        
        # Save to database
        await db.itineraries.insert_one(itinerary.copy())
        
        # Track behavior
        await track_user_behavior(
            current_user['id'],
            "itinerary",
            destination_name=request.destination,
            budget_range=str(request.budget) if request.budget else None
        )
        
        # Send mock email notification
        email_body = f"""
Dear {current_user['name']},

🗓️ Your personalized itinerary is ready!

📋 ITINERARY DETAILS
━━━━━━━━━━━━━━━━━━━━
Destination: {request.destination}
Duration: {request.days} Days
Travel Date: {request.travel_date}
Interests: {request.interests}
{f'Budget: ₹{request.budget:,}' if request.budget else ''}

📥 Your PDF itinerary has been generated and is ready for download.

Preview:
{itinerary_content[:500]}...

Visit your TravelSmart dashboard to download the full PDF.

Happy Planning! 🌍

━━━━━━━━━━━━━━━━━━━━
This is a simulated email notification.
"""
        await send_mock_email(
            current_user['id'],
            current_user['email'],
            "itinerary_generated",
            f"📋 Your {request.destination} Itinerary is Ready!",
            email_body
        )
        
        # Get travel risk index and packing suggestions
        travel_risk_data = await get_travel_risk_index(request.destination, request.budget)
        
        return {
            "success": True,
            "itinerary": {
                "id": itinerary['id'],
                "destination": itinerary['destination'],
                "days": actual_days,
                "requested_days": request.days,
                "content": itinerary_content
            },
            "budget_info": {
                "daily_cost_estimate": avg_cost_per_day,
                "total_estimate": avg_cost_per_day * actual_days,
                "budget_adjusted": actual_days != request.days
            },
            "travel_risk": {
                "score": travel_risk_data.get("risk_score", 70),
                "max_score": 100,
                "category": travel_risk_data.get("category", "Unknown"),
                "recommendation": travel_risk_data.get("recommendation", ""),
                "factors": travel_risk_data.get("risk_factors", [])
            },
            "packing_suggestions": travel_risk_data.get("packing_suggestions", []),
            "pdf_available": True,
            "email_sent": True
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Itinerary generation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Itinerary generation failed")

@api_router.get("/itinerary/list")
async def list_itineraries(current_user: dict = Depends(get_current_user)):
    """Get user's saved itineraries"""
    try:
        itineraries = await db.itineraries.find(
            {"user_id": current_user['id']},
            {"_id": 0}
        ).sort("created_at", -1).to_list(50)
        return {"itineraries": itineraries, "count": len(itineraries)}
    except Exception as e:
        logging.error(f"List itineraries error: {str(e)}")
        return {"itineraries": [], "count": 0}

@api_router.get("/itinerary/{itinerary_id}")
async def get_itinerary(itinerary_id: str, current_user: dict = Depends(get_current_user)):
    """Get specific itinerary"""
    try:
        itinerary = await db.itineraries.find_one(
            {"id": itinerary_id, "user_id": current_user['id']},
            {"_id": 0}
        )
        if not itinerary:
            raise HTTPException(status_code=404, detail="Itinerary not found")
        return itinerary
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Get itinerary error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch itinerary")

@api_router.get("/itinerary/{itinerary_id}/download")
async def download_itinerary(itinerary_id: str, current_user: dict = Depends(get_current_user)):
    """Download itinerary PDF"""
    try:
        itinerary = await db.itineraries.find_one(
            {"id": itinerary_id, "user_id": current_user['id']},
            {"_id": 0}
        )
        if not itinerary:
            raise HTTPException(status_code=404, detail="Itinerary not found")
        
        pdf_path = itinerary.get('pdf_path')
        if not pdf_path or not Path(pdf_path).exists():
            # Regenerate PDF if missing
            user = await db.users.find_one({"id": current_user['id']}, {"_id": 0})
            pdf_path = generate_itinerary_pdf(itinerary, user)
            await db.itineraries.update_one(
                {"id": itinerary_id},
                {"$set": {"pdf_path": pdf_path}}
            )
        
        return FileResponse(
            path=pdf_path,
            media_type='application/pdf',
            filename=f"TravelSmart_Itinerary_{itinerary['destination'].replace(' ', '_')}.pdf"
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Download itinerary error: {str(e)}")
        raise HTTPException(status_code=500, detail="Download failed")


# ===== USER BEHAVIOR & RECOMMENDATIONS =====
@api_router.post("/behavior/track")
async def track_behavior(
    action_type: str,
    destination_id: Optional[str] = None,
    destination_name: Optional[str] = None,
    search_query: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Track user behavior for AI learning"""
    try:
        behavior = await track_user_behavior(
            current_user['id'],
            action_type,
            destination_id=destination_id,
            destination_name=destination_name,
            search_query=search_query
        )
        return {"success": True}
    except Exception as e:
        logging.error(f"Track behavior error: {str(e)}")
        return {"success": False}

@api_router.get("/recommendations/personalized")
async def get_personalized_recommendations(current_user: dict = Depends(get_current_user)):
    """Get AI-powered personalized recommendations based on user behavior"""
    try:
        # Get user behavior
        behaviors = await db.user_behavior.find(
            {"user_id": current_user['id']},
            {"_id": 0}
        ).sort("timestamp", -1).limit(50).to_list(50)
        
        # Get user's bookings
        bookings = await db.bookings.find(
            {"user_id": current_user['id']},
            {"_id": 0}
        ).to_list(20)
        
        # Extract patterns
        viewed_destinations = list(set([b.get('destination_name') for b in behaviors if b.get('destination_name')]))
        booked_destinations = list(set([b.get('item_name') for b in bookings]))
        search_queries = [b.get('search_query') for b in behaviors if b.get('search_query')][:10]
        
        # Get all destinations
        all_destinations = await db.destinations.find({}, {"_id": 0}).to_list(100)
        
        # If no behavior, return popular destinations
        if not behaviors and not bookings:
            popular = sorted(all_destinations, key=lambda x: x.get('rating', 0), reverse=True)[:6]
            return {
                "recommendations": popular,
                "reason": "Popular destinations for you",
                "personalized": False
            }
        
        # Use AI for personalized recommendations
        api_key = os.environ.get('EMERGENT_LLM_KEY')
        
        chat = LlmChat(
            api_key=api_key,
            session_id=f"rec_personal_{current_user['id']}",
            system_message="You are a travel recommendation expert. Analyze user behavior and suggest destinations."
        ).with_model("openai", "gpt-4o-mini")
        
        available_dest = ", ".join([f"{d['name']} ({d['city']}, ₹{d['price']})" for d in all_destinations[:15]])
        
        prompt = f"""Based on this user's behavior, recommend 3-4 destinations from our catalog:

User History:
- Viewed: {', '.join(viewed_destinations[:5]) if viewed_destinations else 'None'}
- Booked: {', '.join(booked_destinations[:5]) if booked_destinations else 'None'}
- Searched: {', '.join(search_queries[:5]) if search_queries else 'None'}

Available Destinations: {available_dest}

Provide recommendations with brief personalized reasons. Format as JSON array with fields: name, reason"""

        user_message = UserMessage(text=prompt)
        ai_response = await chat.send_message(user_message)
        
        # Find matching destinations
        recommended = []
        for dest in all_destinations:
            if dest['name'] in ai_response or dest['city'] in ai_response:
                recommended.append(dest)
                if len(recommended) >= 4:
                    break
        
        # Fallback: top rated not yet booked
        if len(recommended) < 3:
            for dest in sorted(all_destinations, key=lambda x: x.get('rating', 0), reverse=True):
                if dest['name'] not in booked_destinations and dest not in recommended:
                    recommended.append(dest)
                    if len(recommended) >= 4:
                        break
        
        return {
            "recommendations": recommended[:6],
            "reason": "Based on your travel preferences",
            "ai_insight": ai_response,
            "personalized": True
        }
    except Exception as e:
        logging.error(f"Personalized recommendations error: {str(e)}")
        # Fallback to popular
        destinations = await db.destinations.find({}, {"_id": 0}).to_list(100)
        return {
            "recommendations": sorted(destinations, key=lambda x: x.get('rating', 0), reverse=True)[:6],
            "reason": "Popular destinations",
            "personalized": False
        }


# ===== HOTEL INVENTORY ENDPOINTS =====
@api_router.get("/hotels/inventory")
async def get_hotel_inventory():
    """Get all hotels with inventory status"""
    try:
        hotels = await db.destinations.find(
            {"type": "hotel"},
            {"_id": 0}
        ).to_list(100)
        
        # Add inventory status
        for hotel in hotels:
            available = hotel.get('available_rooms', 999)
            total = hotel.get('total_rooms', 999)
            hotel['inventory_status'] = 'sold_out' if available <= 0 else 'low' if available <= 5 else 'available'
        
        return {"hotels": hotels, "count": len(hotels)}
    except Exception as e:
        logging.error(f"Get hotel inventory error: {str(e)}")
        return {"hotels": [], "count": 0}

@api_router.put("/hotels/{hotel_id}/inventory")
async def update_hotel_inventory(
    hotel_id: str,
    total_rooms: Optional[int] = None,
    available_rooms: Optional[int] = None,
    admin_user: dict = Depends(get_admin_user)
):
    """Update hotel inventory (admin only)"""
    try:
        update_fields = {}
        if total_rooms is not None:
            update_fields['total_rooms'] = total_rooms
        if available_rooms is not None:
            update_fields['available_rooms'] = available_rooms
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        result = await db.destinations.update_one(
            {"id": hotel_id, "type": "hotel"},
            {"$set": update_fields}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Hotel not found")
        
        return {"success": True, "updated": update_fields}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Update inventory error: {str(e)}")
        raise HTTPException(status_code=500, detail="Update failed")


# ===== EMAIL LOGS =====
@api_router.get("/emails/logs")
async def get_email_logs(current_user: dict = Depends(get_current_user)):
    """Get user's email notification logs"""
    try:
        logs = await db.email_logs.find(
            {"user_id": current_user['id']},
            {"_id": 0}
        ).sort("created_at", -1).limit(20).to_list(20)
        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        logging.error(f"Get email logs error: {str(e)}")
        return {"logs": [], "count": 0}

# ===== SEED DATA =====
@api_router.post("/seed")
async def seed_data():
    # Force reseed - delete existing data
    await db.destinations.delete_many({})
    
    # Sample destinations data
    destinations = [
        {
            "id": str(uuid.uuid4()),
            "name": "Mumbai Getaway",
            "country": "India",
            "city": "Mumbai",
            "type": "hotel",
            "description": "Experience the bustling financial capital of India with luxury hotels and vibrant nightlife.",
            "price": 25000,
            "duration": "3 Days / 2 Nights",
            "rating": 4.5,
            "image": "https://images.unsplash.com/photo-1554366347-897a5113f6ab",
            "lat": 19.0760,
            "lng": 72.8777,
            "total_rooms": 50,
            "available_rooms": 45
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Delhi Heritage Tour",
            "country": "India",
            "city": "Delhi",
            "type": "tour",
            "description": "Explore historic monuments, bustling markets, and authentic North Indian cuisine.",
            "price": 22000,
            "duration": "4 Days / 3 Nights",
            "rating": 4.6,
            "image": "https://images.unsplash.com/photo-1605130284535-11dd9eedc58a",
            "lat": 28.6139,
            "lng": 77.2090
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Dubai Luxury Experience",
            "country": "UAE",
            "city": "Dubai",
            "type": "hotel",
            "description": "World-class luxury hotels, shopping malls, and stunning architecture in the desert.",
            "price": 85000,
            "duration": "5 Days / 4 Nights",
            "rating": 4.9,
            "image": "https://images.pexels.com/photos/34519516/pexels-photo-34519516.jpeg",
            "lat": 25.2048,
            "lng": 55.2708,
            "total_rooms": 30,
            "available_rooms": 25
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Singapore City Break",
            "country": "Singapore",
            "city": "Singapore",
            "type": "tour",
            "description": "Gardens by the Bay, Marina Bay Sands, and multicultural food paradise.",
            "price": 65000,
            "duration": "4 Days / 3 Nights",
            "rating": 4.8,
            "image": "https://images.unsplash.com/photo-1540541338287-41700207dee6",
            "lat": 1.3521,
            "lng": 103.8198
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Bangkok Adventure",
            "country": "Thailand",
            "city": "Bangkok",
            "type": "tour",
            "description": "Golden temples, floating markets, and amazing street food.",
            "price": 35000,
            "duration": "5 Days / 4 Nights",
            "rating": 4.7,
            "image": "https://images.unsplash.com/photo-1549294413-26f195200c16",
            "lat": 13.7563,
            "lng": 100.5018
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Tokyo Discovery",
            "country": "Japan",
            "city": "Tokyo",
            "type": "tour",
            "description": "Modern technology meets ancient tradition in Japan's vibrant capital.",
            "price": 95000,
            "duration": "6 Days / 5 Nights",
            "rating": 4.9,
            "image": "https://images.unsplash.com/photo-1436491865332-7a61a109cc05",
            "lat": 35.6762,
            "lng": 139.6503
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Paris Romantic Escape",
            "country": "France",
            "city": "Paris",
            "type": "hotel",
            "description": "City of lights, Eiffel Tower, Louvre Museum, and world-class cuisine.",
            "price": 125000,
            "duration": "6 Days / 5 Nights",
            "rating": 4.9,
            "image": "https://images.unsplash.com/photo-1524661135-423995f22d0b",
            "lat": 48.8566,
            "lng": 2.3522,
            "total_rooms": 40,
            "available_rooms": 35
        },
        {
            "id": str(uuid.uuid4()),
            "name": "London Explorer",
            "country": "UK",
            "city": "London",
            "type": "tour",
            "description": "Historic landmarks, British culture, and West End shows.",
            "price": 115000,
            "duration": "5 Days / 4 Nights",
            "rating": 4.8,
            "image": "https://images.unsplash.com/photo-1652535922604-ca145a2ec554",
            "lat": 51.5074,
            "lng": -0.1278
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Rome Historical Journey",
            "country": "Italy",
            "city": "Rome",
            "type": "tour",
            "description": "Ancient Colosseum, Vatican City, and authentic Italian pasta.",
            "price": 98000,
            "duration": "5 Days / 4 Nights",
            "rating": 4.8,
            "image": "https://images.pexels.com/photos/6862444/pexels-photo-6862444.jpeg",
            "lat": 41.9028,
            "lng": 12.4964
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Berlin Cultural Experience",
            "country": "Germany",
            "city": "Berlin",
            "type": "tour",
            "description": "Rich history, vibrant art scene, and modern German culture.",
            "price": 92000,
            "duration": "4 Days / 3 Nights",
            "rating": 4.6,
            "image": "https://images.unsplash.com/photo-1713098965471-d324f294a71d",
            "lat": 52.5200,
            "lng": 13.4050
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Amsterdam Canal Tour",
            "country": "Netherlands",
            "city": "Amsterdam",
            "type": "tour",
            "description": "Picturesque canals, cycling culture, and world-famous museums.",
            "price": 88000,
            "duration": "4 Days / 3 Nights",
            "rating": 4.7,
            "image": "https://images.unsplash.com/photo-1674027444485-cec3da58eef4",
            "lat": 52.3676,
            "lng": 4.9041
        },
        {
            "id": str(uuid.uuid4()),
            "name": "New York City Adventure",
            "country": "USA",
            "city": "New York",
            "type": "hotel",
            "description": "Statue of Liberty, Times Square, Central Park, and Broadway shows.",
            "price": 145000,
            "duration": "6 Days / 5 Nights",
            "rating": 4.9,
            "image": "https://images.pexels.com/photos/9028921/pexels-photo-9028921.jpeg",
            "lat": 40.7128,
            "lng": -74.0060,
            "total_rooms": 60,
            "available_rooms": 55
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Sydney Harbour Experience",
            "country": "Australia",
            "city": "Sydney",
            "type": "hotel",
            "description": "Opera House, Harbour Bridge, beautiful beaches, and wildlife.",
            "price": 135000,
            "duration": "7 Days / 6 Nights",
            "rating": 4.8,
            "image": "https://images.unsplash.com/photo-1605130284535-11dd9eedc58a",
            "lat": -33.8688,
            "lng": 151.2093,
            "total_rooms": 45,
            "available_rooms": 40
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Melbourne Coffee Culture",
            "country": "Australia",
            "city": "Melbourne",
            "type": "tour",
            "description": "Laneway cafes, street art, and multicultural food scene.",
            "price": 128000,
            "duration": "6 Days / 5 Nights",
            "rating": 4.7,
            "image": "https://images.unsplash.com/photo-1554366347-897a5113f6ab",
            "lat": -37.8136,
            "lng": 144.9631
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Cape Town Safari & Beach",
            "country": "South Africa",
            "city": "Cape Town",
            "type": "tour",
            "description": "Table Mountain, stunning beaches, and African wildlife safari.",
            "price": 105000,
            "duration": "7 Days / 6 Nights",
            "rating": 4.8,
            "image": "https://images.pexels.com/photos/34519516/pexels-photo-34519516.jpeg",
            "lat": -33.9249,
            "lng": 18.4241
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Cairo Pyramid Tour",
            "country": "Egypt",
            "city": "Cairo",
            "type": "tour",
            "description": "Ancient pyramids, Sphinx, and Nile River cruise.",
            "price": 68000,
            "duration": "5 Days / 4 Nights",
            "rating": 4.7,
            "image": "https://images.unsplash.com/photo-1540541338287-41700207dee6",
            "lat": 30.0444,
            "lng": 31.2357
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Goa Beach Paradise",
            "country": "India",
            "city": "Goa",
            "type": "hotel",
            "description": "Pristine beaches, Portuguese heritage, and vibrant nightlife.",
            "price": 18000,
            "duration": "3 Days / 2 Nights",
            "rating": 4.6,
            "image": "https://images.unsplash.com/photo-1549294413-26f195200c16",
            "lat": 15.2993,
            "lng": 74.1240,
            "total_rooms": 35,
            "available_rooms": 30
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Bali Tropical Retreat",
            "country": "Indonesia",
            "city": "Bali",
            "type": "hotel",
            "description": "Lush rice terraces, ancient temples, and pristine beaches.",
            "price": 42000,
            "duration": "5 Days / 4 Nights",
            "rating": 4.8,
            "image": "https://images.pexels.com/photos/6862444/pexels-photo-6862444.jpeg",
            "lat": -8.3405,
            "lng": 115.0920,
            "total_rooms": 25,
            "available_rooms": 20
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Maldives Luxury Resort",
            "country": "Maldives",
            "city": "Male",
            "type": "hotel",
            "description": "Overwater bungalows, crystal clear waters, and world-class diving.",
            "price": 175000,
            "duration": "5 Days / 4 Nights",
            "rating": 5.0,
            "image": "https://images.unsplash.com/photo-1436491865332-7a61a109cc05",
            "lat": 4.1755,
            "lng": 73.5093
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Barcelona Gaudi Tour",
            "country": "Spain",
            "city": "Barcelona",
            "type": "tour",
            "description": "Sagrada Familia, Park Güell, Gothic Quarter, and tapas.",
            "price": 95000,
            "duration": "5 Days / 4 Nights",
            "rating": 4.8,
            "image": "https://images.unsplash.com/photo-1652535922604-ca145a2ec554",
            "lat": 41.3851,
            "lng": 2.1734
        }
    ]
    
    await db.destinations.insert_many(destinations)
    
    # Create demo user
    demo_user = User(
        email="demo@travelapp.com",
        password_hash=hash_password("demo123"),
        name="Demo User"
    )
    doc = demo_user.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.users.insert_one(doc)
    
    # Create admin user
    admin_user = User(
        email="admin@travelsmart.com",
        password_hash=hash_password("Admin@123"),
        name="Admin User",
        role="admin"
    )
    admin_doc = admin_user.model_dump()
    admin_doc['created_at'] = admin_doc['created_at'].isoformat()
    await db.users.insert_one(admin_doc)
    
    return {"message": "Database seeded successfully", "destinations": len(destinations), "admin_created": True}

# ===== STRIPE PAYMENT ENDPOINTS =====

class StripeCheckoutRequest(BaseModel):
    booking_id: str
    origin_url: str

@api_router.post("/payments/create-checkout")
async def create_stripe_checkout(data: StripeCheckoutRequest, request: Request, current_user: dict = Depends(get_current_user)):
    """Create a Stripe Checkout Session for a booking"""
    try:
        # Get booking - amount comes from backend, never from frontend
        booking = await db.bookings.find_one(
            {"id": data.booking_id, "user_id": current_user['id']},
            {"_id": 0}
        )
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        # Prevent duplicate payments
        existing_paid = await db.payment_transactions.find_one(
            {"booking_id": data.booking_id, "payment_status": "paid"},
            {"_id": 0}
        )
        if existing_paid:
            raise HTTPException(status_code=400, detail="This booking has already been paid for")

        # Get amount from the booking (server-side, never from frontend)
        amount = float(booking.get('amount', 0))
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Invalid booking amount")

        # Convert INR to proper float format
        amount_float = float(amount)

        # Build dynamic URLs from frontend origin
        origin = data.origin_url.rstrip('/')
        success_url = f"{origin}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{origin}/booking/{booking.get('item_id', booking.get('destination_id', ''))}"

        # Initialize Stripe checkout
        stripe_api_key = os.environ.get('STRIPE_API_KEY')
        if not stripe_api_key:
            raise HTTPException(status_code=500, detail="Payment service not configured")

        host_url = str(request.base_url)
        webhook_url = f"{host_url}api/webhook/stripe"
        stripe_checkout = StripeCheckout(api_key=stripe_api_key, webhook_url=webhook_url)

        # Create checkout session
        metadata = {
            "booking_id": data.booking_id,
            "user_id": current_user['id'],
            "user_email": current_user['email'],
            "destination": booking.get('item_name', booking.get('destination_name', 'Travel Booking'))
        }

        checkout_request = CheckoutSessionRequest(
            amount=amount_float,
            currency="inr",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata
        )

        session: CheckoutSessionResponse = await stripe_checkout.create_checkout_session(checkout_request)

        # Create payment transaction record
        transaction = {
            "id": str(uuid.uuid4()),
            "session_id": session.session_id,
            "booking_id": data.booking_id,
            "user_id": current_user['id'],
            "user_email": current_user['email'],
            "amount": amount_float,
            "currency": "inr",
            "payment_status": "initiated",
            "status": "pending",
            "metadata": metadata,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.payment_transactions.insert_one(transaction)

        return {
            "checkout_url": session.url,
            "session_id": session.session_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Stripe checkout error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Payment initialization failed: {str(e)}")


@api_router.get("/payments/checkout-status/{session_id}")
async def get_checkout_status(session_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Poll the status of a Stripe checkout session"""
    try:
        # Check if already processed to prevent duplicate updates
        existing_txn = await db.payment_transactions.find_one(
            {"session_id": session_id},
            {"_id": 0}
        )
        if not existing_txn:
            raise HTTPException(status_code=404, detail="Payment transaction not found")

        # If already marked as paid, return immediately
        if existing_txn.get('payment_status') == 'paid':
            return {
                "status": "complete",
                "payment_status": "paid",
                "booking_id": existing_txn.get('booking_id'),
                "amount": existing_txn.get('amount'),
                "transaction_id": existing_txn.get('id')
            }

        # Initialize Stripe and check status
        stripe_api_key = os.environ.get('STRIPE_API_KEY')
        host_url = str(request.base_url)
        webhook_url = f"{host_url}api/webhook/stripe"
        stripe_checkout = StripeCheckout(api_key=stripe_api_key, webhook_url=webhook_url)

        checkout_status: CheckoutStatusResponse = await stripe_checkout.get_checkout_status(session_id)

        # Update payment transaction based on Stripe status
        new_status = checkout_status.payment_status
        update_data = {
            "payment_status": new_status,
            "status": checkout_status.status,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        # If payment is successful, update booking status too
        if new_status == "paid" and existing_txn.get('payment_status') != 'paid':
            update_data["payment_status"] = "paid"

            # Update the payment transaction
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": update_data}
            )

            # Update booking status to confirmed
            booking_id = existing_txn.get('booking_id')
            await db.bookings.update_one(
                {"id": booking_id},
                {"$set": {"status": "Confirmed (Paid)", "paid_at": datetime.now(timezone.utc).isoformat()}}
            )

            # Generate invoice
            booking = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
            user = await db.users.find_one({"id": current_user['id']}, {"_id": 0})
            if booking and user:
                payment_doc = {
                    "transaction_id": f"STR-{session_id[:8].upper()}",
                    "amount": existing_txn.get('amount'),
                    "status": "success",
                    "payment_method": "stripe"
                }
                try:
                    generate_invoice_pdf(booking, payment_doc, user)
                except Exception as inv_err:
                    logging.error(f"Invoice generation error: {inv_err}")

                # Send confirmation email
                await send_mock_email(
                    current_user['id'],
                    current_user['email'],
                    "payment_confirmation",
                    f"Payment Confirmed - {booking.get('item_name', 'Booking')}",
                    f"Payment of INR {existing_txn.get('amount'):,.0f} received successfully for {booking.get('item_name', 'your booking')}. Transaction: STR-{session_id[:8].upper()}"
                )

            return {
                "status": "complete",
                "payment_status": "paid",
                "booking_id": booking_id,
                "amount": existing_txn.get('amount'),
                "transaction_id": existing_txn.get('id')
            }
        else:
            # Update transaction with current status
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": update_data}
            )

            return {
                "status": checkout_status.status,
                "payment_status": new_status,
                "booking_id": existing_txn.get('booking_id'),
                "amount": existing_txn.get('amount')
            }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Checkout status error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")


@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    try:
        body = await request.body()
        signature = request.headers.get("Stripe-Signature", "")

        stripe_api_key = os.environ.get('STRIPE_API_KEY')
        host_url = str(request.base_url)
        webhook_url = f"{host_url}api/webhook/stripe"
        stripe_checkout = StripeCheckout(api_key=stripe_api_key, webhook_url=webhook_url)

        webhook_response = await stripe_checkout.handle_webhook(body, signature)

        if webhook_response.payment_status == "paid":
            session_id = webhook_response.session_id
            # Prevent duplicate processing
            existing = await db.payment_transactions.find_one(
                {"session_id": session_id, "payment_status": "paid"},
                {"_id": 0}
            )
            if not existing:
                await db.payment_transactions.update_one(
                    {"session_id": session_id},
                    {"$set": {
                        "payment_status": "paid",
                        "status": "complete",
                        "webhook_event_id": webhook_response.event_id,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
                # Update booking
                txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
                if txn:
                    await db.bookings.update_one(
                        {"id": txn.get('booking_id')},
                        {"$set": {"status": "Confirmed (Paid)", "paid_at": datetime.now(timezone.utc).isoformat()}}
                    )

        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Webhook error: {str(e)}")
        return {"status": "error", "detail": str(e)}


# ===== E-TICKET PDF GENERATION =====
def generate_ticket_pdf(booking: dict, user: dict) -> str:
    """Generate a travel e-ticket PDF"""
    tickets_dir = ROOT_DIR / "tickets"
    tickets_dir.mkdir(exist_ok=True)
    filename = f"ticket_{booking['id']}.pdf"
    filepath = tickets_dir / filename
    doc = SimpleDocTemplate(str(filepath), pagesize=letter)
    story = []
    styles = getSampleStyleSheet()

    # Header
    header_style = ParagraphStyle('TicketHeader', parent=styles['Heading1'], fontSize=28,
        textColor=colors.HexColor('#1e40af'), spaceAfter=10, alignment=1)
    story.append(Paragraph("TravelSmart E-Ticket", header_style))
    story.append(Spacer(1, 0.1*inch))

    sub_style = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=11, textColor=colors.grey, alignment=1)
    story.append(Paragraph("Electronic Travel Ticket - Please present at check-in", sub_style))
    story.append(Spacer(1, 0.3*inch))

    # Ticket details table
    dest_name = booking.get('item_name', booking.get('destination_name', 'N/A'))
    booking_ref = booking['id'][:8].upper()
    status = booking.get('status', 'Confirmed')
    base_amt = booking.get('base_amount', booking.get('amount', 0))
    fee = booking.get('service_fee', 0)
    total = booking.get('amount', base_amt)

    data = [
        ['BOOKING REFERENCE', booking_ref],
        ['PASSENGER', user.get('name', 'N/A')],
        ['EMAIL', user.get('email', 'N/A')],
        ['DESTINATION', dest_name],
        ['TYPE', booking.get('item_type', 'N/A').upper()],
        ['TRAVEL DATE', booking.get('travel_date', 'N/A')],
        ['TRAVELERS', str(booking.get('travelers', 1))],
        ['BASE AMOUNT', f"INR {base_amt:,}"],
        ['SERVICE FEE (5%)', f"INR {fee:,}"],
        ['TOTAL PAID', f"INR {total:,}"],
        ['STATUS', status.upper()],
    ]
    table = Table(data, colWidths=[2.2*inch, 4*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#eff6ff')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1e40af')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#dcfce7')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.4*inch))

    # Terms
    terms_style = ParagraphStyle('Terms', parent=styles['Normal'], fontSize=9, textColor=colors.grey)
    story.append(Paragraph("<b>Terms:</b> Free cancellation 24hrs before travel. 50% refund within 24hrs. No refund for no-shows.", terms_style))
    story.append(Spacer(1, 0.2*inch))

    footer = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=10, textColor=colors.grey, alignment=1)
    story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%B %d, %Y %H:%M UTC')}", footer))
    story.append(Paragraph("TravelSmart - AI-Powered Travel Booking Platform", footer))
    doc.build(story)
    return str(filepath)


@api_router.get("/ticket/{booking_id}")
async def download_ticket(booking_id: str, current_user: dict = Depends(get_current_user)):
    """Download e-ticket PDF for a booking"""
    booking = await db.bookings.find_one({"id": booking_id, "user_id": current_user['id']}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    user = await db.users.find_one({"id": current_user['id']}, {"_id": 0})
    ticket_path = ROOT_DIR / "tickets" / f"ticket_{booking_id}.pdf"
    if not ticket_path.exists():
        generate_ticket_pdf(booking, user)
    return FileResponse(path=str(ticket_path), media_type='application/pdf',
        filename=f"TravelSmart_Ticket_{booking_id[:8]}.pdf")


# ===== ENHANCED ADMIN ENDPOINTS =====

class DestinationCreate(BaseModel):
    name: str
    country: str
    city: str
    type: str
    description: str
    price: int
    duration: str
    rating: float = 4.0
    image: str = ""
    lat: float = 0.0
    lng: float = 0.0
    total_rooms: Optional[int] = None
    available_rooms: Optional[int] = None

class DestinationUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    duration: Optional[str] = None
    rating: Optional[float] = None
    image: Optional[str] = None
    total_rooms: Optional[int] = None
    available_rooms: Optional[int] = None

@api_router.post("/admin/destinations")
async def create_destination(data: DestinationCreate, admin_user: dict = Depends(get_admin_user)):
    """Admin: Create a new destination"""
    dest = {
        "id": str(uuid.uuid4()),
        **data.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.destinations.insert_one(dest)
    return {"success": True, "destination": {k: v for k, v in dest.items() if k != '_id'}}

@api_router.put("/admin/destinations/{dest_id}")
async def update_destination(dest_id: str, data: DestinationUpdate, admin_user: dict = Depends(get_admin_user)):
    """Admin: Update a destination"""
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await db.destinations.update_one({"id": dest_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Destination not found")
    return {"success": True, "updated_fields": list(update_data.keys())}

@api_router.delete("/admin/destinations/{dest_id}")
async def delete_destination(dest_id: str, admin_user: dict = Depends(get_admin_user)):
    """Admin: Delete a destination"""
    result = await db.destinations.delete_one({"id": dest_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Destination not found")
    return {"success": True}

@api_router.get("/admin/bookings")
async def get_all_bookings(admin_user: dict = Depends(get_admin_user)):
    """Admin: Get all bookings across all users"""
    bookings = await db.bookings.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"bookings": bookings, "count": len(bookings)}

@api_router.put("/admin/bookings/{booking_id}/status")
async def update_booking_status(booking_id: str, admin_user: dict = Depends(get_admin_user)):
    """Admin: This is accessed via query param ?status=xxx"""
    # We'll handle this via request
    pass

@api_router.get("/admin/revenue")
async def get_revenue_report(admin_user: dict = Depends(get_admin_user)):
    """Admin: Revenue report"""
    try:
        # All paid transactions
        paid_txns = await db.payment_transactions.find(
            {"payment_status": "paid"}, {"_id": 0}
        ).to_list(1000)

        # All bookings
        all_bookings = await db.bookings.find({}, {"_id": 0}).to_list(1000)

        total_revenue = sum(t.get('amount', 0) for t in paid_txns)
        total_service_fees = sum(b.get('service_fee', 0) for b in all_bookings if 'paid' in b.get('status', '').lower())
        total_base_revenue = total_revenue - total_service_fees

        # Booking status breakdown
        status_counts = {}
        for b in all_bookings:
            s = b.get('status', 'unknown')
            status_counts[s] = status_counts.get(s, 0) + 1

        # Revenue by destination
        dest_revenue = {}
        for b in all_bookings:
            if 'paid' in b.get('status', '').lower():
                name = b.get('item_name', b.get('destination_name', 'Unknown'))
                dest_revenue[name] = dest_revenue.get(name, 0) + b.get('amount', 0)
        top_revenue_dests = sorted(dest_revenue.items(), key=lambda x: x[1], reverse=True)[:10]

        # Monthly revenue (last 6 months)
        monthly = {}
        for t in paid_txns:
            created = t.get('created_at', '')
            if created:
                month_key = created[:7]  # YYYY-MM
                monthly[month_key] = monthly.get(month_key, 0) + t.get('amount', 0)

        return {
            "total_revenue": total_revenue,
            "total_service_fees": total_service_fees,
            "total_base_revenue": total_base_revenue,
            "service_fee_percent": SERVICE_FEE_PERCENT,
            "total_transactions": len(paid_txns),
            "total_bookings": len(all_bookings),
            "booking_status_breakdown": status_counts,
            "top_revenue_destinations": [{"name": n, "revenue": r} for n, r in top_revenue_dests],
            "monthly_revenue": [{"month": k, "revenue": v} for k, v in sorted(monthly.items())],
            "pending_payments": sum(1 for b in all_bookings if 'pending' in b.get('status', '').lower()),
        }
    except Exception as e:
        logging.error(f"Revenue report error: {str(e)}")
        raise HTTPException(status_code=500, detail="Revenue report failed")

@api_router.put("/admin/users/{user_id}/role")
async def update_user_role(user_id: str, admin_user: dict = Depends(get_admin_user)):
    """Admin: Toggle user role between user and admin"""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    new_role = "admin" if user.get('role') == 'user' else "user"
    await db.users.update_one({"id": user_id}, {"$set": {"role": new_role}})
    return {"success": True, "new_role": new_role}

@api_router.get("/admin/emails")
async def get_email_logs(admin_user: dict = Depends(get_admin_user)):
    """Admin: Get email delivery logs"""
    emails = await db.email_logs.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
    stats = {
        "total": len(emails),
        "delivered": sum(1 for e in emails if e.get('status') == 'delivered'),
        "mock": sum(1 for e in emails if e.get('status') == 'mock'),
        "failed": sum(1 for e in emails if 'error' in e),
    }
    return {"emails": emails, "stats": stats}


# Include router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
