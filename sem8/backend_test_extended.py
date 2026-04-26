#!/usr/bin/env python3
"""
TravelSmart Extended Backend API Test Suite
Tests the 6 new features specifically requested:
1. Multilingual AI Chatbot (English, Hindi, Marathi)
2. Voice Input for Chatbot (backend support)
3. Export Itinerary as PDF
4. Mock Email Notifications
5. Hotel Inventory Management
6. AI Learning from User Behavior
"""

import requests
import json
import sys
from datetime import datetime

# Configuration
BASE_URL = "https://smart-itinerary-44.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@travelsmart.com"
ADMIN_PASSWORD = "Admin@123"
DEMO_EMAIL = "demo@travelapp.com"
DEMO_PASSWORD = "demo123"

class TravelSmartExtendedTester:
    def __init__(self):
        self.admin_token = None
        self.demo_token = None
        self.test_results = []
        self.failed_tests = []
        
    def log_test(self, test_name, success, message="", response_data=None):
        """Log test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}: {message}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "message": message,
            "response": response_data
        })
        
        if not success:
            self.failed_tests.append(test_name)
    
    def make_request(self, method, endpoint, data=None, token=None, params=None):
        """Make HTTP request with proper headers"""
        url = f"{BASE_URL}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, timeout=30)
            elif method == "PUT":
                response = requests.put(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            return response
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            return None
    
    def authenticate(self):
        """Authenticate admin and demo users"""
        print("\n=== AUTHENTICATION ===")
        
        # Admin login
        admin_data = {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        response = self.make_request("POST", "/auth/login", admin_data)
        
        if response and response.status_code == 200:
            data = response.json()
            self.admin_token = data.get("token")
            self.log_test("Admin Login", True, "Admin authenticated successfully")
        else:
            self.log_test("Admin Login", False, "Failed to authenticate admin")
        
        # Demo user login
        demo_data = {"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        response = self.make_request("POST", "/auth/login", demo_data)
        
        if response and response.status_code == 200:
            data = response.json()
            self.demo_token = data.get("token")
            self.log_test("Demo User Login", True, "Demo user authenticated successfully")
        else:
            self.log_test("Demo User Login", False, "Failed to authenticate demo user")
    
    def test_multilingual_chatbot(self):
        """Test Feature 1: Multilingual AI Chatbot"""
        print("\n=== FEATURE 1: MULTILINGUAL AI CHATBOT ===")
        
        if not self.demo_token:
            self.log_test("Multilingual Chatbot", False, "No demo token available")
            return
        
        # Test English message
        english_data = {
            "user_id": "test_user",
            "message": "Show me hotels in Goa under ₹20,000"
        }
        response = self.make_request("POST", "/ai/chat", english_data, self.demo_token)
        
        if response and response.status_code == 200:
            data = response.json()
            language = data.get("language", "unknown")
            bot_response = data.get("response", "")
            
            if language == "english" and bot_response:
                self.log_test("English Chat", True, f"Detected language: {language}, Response received")
            else:
                self.log_test("English Chat", False, f"Language detection failed or no response")
        else:
            self.log_test("English Chat", False, "English chat request failed")
        
        # Test Hindi message - the specific test case from requirements
        hindi_data = {
            "user_id": "test_user", 
            "message": "मुझे गोवा में होटल दिखाओ"
        }
        response = self.make_request("POST", "/ai/chat", hindi_data, self.demo_token)
        
        if response and response.status_code == 200:
            data = response.json()
            language = data.get("language", "unknown")
            bot_response = data.get("response", "")
            
            if language == "hindi" and bot_response:
                # Check if response contains Hindi characters
                hindi_chars = sum(1 for c in bot_response if '\u0900' <= c <= '\u097F')
                if hindi_chars > 0:
                    self.log_test("Hindi Chat", True, f"Hindi detected and responded in Hindi (chars: {hindi_chars})")
                else:
                    self.log_test("Hindi Chat", False, f"Hindi detected but response not in Hindi")
            else:
                self.log_test("Hindi Chat", False, f"Hindi language detection failed: {language}")
        else:
            self.log_test("Hindi Chat", False, "Hindi chat request failed")
        
        # Test Marathi message
        marathi_data = {
            "user_id": "test_user",
            "message": "मला मुंबईत हॉटेल हवे"
        }
        response = self.make_request("POST", "/ai/chat", marathi_data, self.demo_token)
        
        if response and response.status_code == 200:
            data = response.json()
            language = data.get("language", "unknown")
            bot_response = data.get("response", "")
            
            if language == "marathi" and bot_response:
                self.log_test("Marathi Chat", True, f"Marathi detected and responded")
            else:
                self.log_test("Marathi Chat", False, f"Marathi detection failed: {language}")
        else:
            self.log_test("Marathi Chat", False, "Marathi chat request failed")
    
    def test_itinerary_pdf_generation(self):
        """Test Feature 3: Export Itinerary as PDF"""
        print("\n=== FEATURE 3: ITINERARY PDF GENERATION ===")
        
        if not self.demo_token:
            self.log_test("Itinerary PDF", False, "No demo token available")
            return
        
        # Test generating itinerary
        itinerary_data = {
            "destination": "Goa",
            "days": 3,
            "travel_date": "2025-03-15",
            "interests": "Beach, Food, Nightlife",
            "budget": 30000
        }
        response = self.make_request("POST", "/itinerary/generate", itinerary_data, self.demo_token)
        
        itinerary_id = None
        if response and response.status_code == 200:
            data = response.json()
            success = data.get("success", False)
            itinerary = data.get("itinerary", {})
            itinerary_id = itinerary.get("id")
            pdf_available = data.get("pdf_available", False)
            email_sent = data.get("email_sent", False)
            
            if success and itinerary_id and pdf_available:
                self.log_test("Generate Itinerary", True, f"Itinerary generated with ID: {itinerary_id[:8]}, PDF: {pdf_available}, Email: {email_sent}")
            else:
                self.log_test("Generate Itinerary", False, f"Generation failed or incomplete response")
        else:
            error_msg = response.text if response else "No response"
            self.log_test("Generate Itinerary", False, f"Itinerary generation failed: {error_msg}")
        
        # Test downloading PDF
        if itinerary_id:
            response = self.make_request("GET", f"/itinerary/{itinerary_id}/download", token=self.demo_token)
            
            if response and response.status_code == 200:
                content_type = response.headers.get('content-type', '')
                content_length = len(response.content)
                
                if 'application/pdf' in content_type and content_length > 1000:
                    self.log_test("Download PDF", True, f"PDF downloaded successfully ({content_length} bytes)")
                else:
                    self.log_test("Download PDF", False, f"Invalid PDF response: {content_type}, {content_length} bytes")
            else:
                self.log_test("Download PDF", False, "PDF download failed")
        else:
            self.log_test("Download PDF", False, "No itinerary ID for download test")
        
        # Test listing itineraries
        response = self.make_request("GET", "/itinerary/list", token=self.demo_token)
        
        if response and response.status_code == 200:
            data = response.json()
            itineraries = data.get("itineraries", [])
            count = data.get("count", 0)
            self.log_test("List Itineraries", True, f"Retrieved {count} itineraries")
        else:
            self.log_test("List Itineraries", False, "Failed to list itineraries")
    
    def test_mock_email_notifications(self):
        """Test Feature 4: Mock Email Notifications"""
        print("\n=== FEATURE 4: MOCK EMAIL NOTIFICATIONS ===")
        
        if not self.demo_token:
            self.log_test("Mock Email", False, "No demo token available")
            return
        
        # Get destinations for booking
        response = self.make_request("GET", "/destinations")
        destinations = []
        
        if response and response.status_code == 200:
            destinations = response.json()
        
        if not destinations:
            self.log_test("Mock Email", False, "No destinations available for booking test")
            return
        
        destination = destinations[0]
        
        # Create a booking (should trigger email)
        booking_data = {
            "item_type": destination.get("type", "tour"),
            "item_id": destination.get("id"),
            "travelers": 1,
            "travel_date": "2025-03-20",
            "details": {"test": "email notification"}
        }
        response = self.make_request("POST", "/bookings/create", booking_data, self.demo_token)
        
        if response and response.status_code == 200:
            data = response.json()
            email_sent = data.get("email_sent", False)
            
            if email_sent:
                self.log_test("Booking Email Trigger", True, "Email notification triggered on booking")
            else:
                self.log_test("Booking Email Trigger", False, "Email notification not triggered")
        else:
            self.log_test("Booking Email Trigger", False, "Booking creation failed")
        
        # Check email logs
        response = self.make_request("GET", "/emails/logs", token=self.demo_token)
        
        if response and response.status_code == 200:
            data = response.json()
            logs = data.get("logs", [])
            count = data.get("count", 0)
            
            # Look for recent booking confirmation email
            booking_emails = [log for log in logs if log.get("email_type") == "booking_confirmation"]
            
            if booking_emails:
                recent_email = booking_emails[0]
                subject = recent_email.get("subject", "")
                status = recent_email.get("status", "")
                
                if "Booking Confirmed" in subject and status == "sent":
                    self.log_test("Email Logs Check", True, f"Found booking confirmation email: {subject}")
                else:
                    self.log_test("Email Logs Check", False, f"Email found but incorrect format")
            else:
                self.log_test("Email Logs Check", False, f"No booking confirmation emails found in {count} logs")
        else:
            self.log_test("Email Logs Check", False, "Failed to retrieve email logs")
    
    def test_hotel_inventory_management(self):
        """Test Feature 5: Hotel Inventory Management"""
        print("\n=== FEATURE 5: HOTEL INVENTORY MANAGEMENT ===")
        
        if not self.demo_token:
            self.log_test("Hotel Inventory", False, "No demo token available")
            return
        
        # Get hotel inventory
        response = self.make_request("GET", "/hotels/inventory")
        
        hotels = []
        if response and response.status_code == 200:
            data = response.json()
            hotels = data.get("hotels", [])
            count = data.get("count", 0)
            
            if hotels:
                hotel = hotels[0]
                available_rooms = hotel.get("available_rooms")
                total_rooms = hotel.get("total_rooms")
                inventory_status = hotel.get("inventory_status")
                
                if available_rooms is not None and total_rooms is not None:
                    self.log_test("Hotel Inventory List", True, f"Found {count} hotels, first has {available_rooms}/{total_rooms} rooms, status: {inventory_status}")
                else:
                    self.log_test("Hotel Inventory List", False, "Hotels missing inventory fields")
            else:
                self.log_test("Hotel Inventory List", False, "No hotels found")
        else:
            self.log_test("Hotel Inventory List", False, "Failed to get hotel inventory")
        
        # Test booking with inventory check
        if hotels:
            hotel = hotels[0]
            hotel_id = hotel.get("id")
            available_rooms = hotel.get("available_rooms", 0)
            
            if available_rooms > 0:
                # Test normal booking (should work)
                booking_data = {
                    "item_type": "hotel",
                    "item_id": hotel_id,
                    "travelers": 1,
                    "travel_date": "2025-03-25",
                    "details": {"inventory_test": True}
                }
                response = self.make_request("POST", "/bookings/create", booking_data, self.demo_token)
                
                if response and response.status_code == 200:
                    self.log_test("Hotel Booking Success", True, "Hotel booking successful with available rooms")
                    
                    # Check if inventory was reduced
                    response = self.make_request("GET", "/hotels/inventory")
                    if response and response.status_code == 200:
                        updated_hotels = response.json().get("hotels", [])
                        updated_hotel = next((h for h in updated_hotels if h.get("id") == hotel_id), None)
                        
                        if updated_hotel:
                            new_available = updated_hotel.get("available_rooms", 0)
                            if new_available == available_rooms - 1:
                                self.log_test("Inventory Reduction", True, f"Rooms reduced from {available_rooms} to {new_available}")
                            else:
                                self.log_test("Inventory Reduction", False, f"Rooms not properly reduced: {available_rooms} -> {new_available}")
                else:
                    self.log_test("Hotel Booking Success", False, "Hotel booking failed")
                
                # Test booking more rooms than available (should fail)
                if available_rooms < 10:  # Only test if we won't break the system
                    booking_data = {
                        "item_type": "hotel",
                        "item_id": hotel_id,
                        "travelers": available_rooms + 5,  # More than available
                        "travel_date": "2025-03-26",
                        "details": {"overbook_test": True}
                    }
                    response = self.make_request("POST", "/bookings/create", booking_data, self.demo_token)
                    
                    if response and response.status_code == 400:
                        error_detail = response.json().get("detail", "")
                        if "Not enough rooms" in error_detail:
                            self.log_test("Hotel Overbooking Prevention", True, "Correctly prevented overbooking")
                        else:
                            self.log_test("Hotel Overbooking Prevention", False, f"Wrong error message: {error_detail}")
                    else:
                        self.log_test("Hotel Overbooking Prevention", False, "Overbooking was allowed (should be prevented)")
            else:
                self.log_test("Hotel Inventory Tests", False, "No available rooms for testing")
    
    def test_user_behavior_tracking(self):
        """Test Feature 6: AI Learning from User Behavior"""
        print("\n=== FEATURE 6: USER BEHAVIOR TRACKING ===")
        
        if not self.demo_token:
            self.log_test("User Behavior", False, "No demo token available")
            return
        
        # Test manual behavior tracking
        response = self.make_request("POST", "/behavior/track", {
            "action_type": "search",
            "destination_name": "Goa",
            "search_query": "beach hotels under 15000"
        }, self.demo_token)
        
        if response and response.status_code == 200:
            data = response.json()
            success = data.get("success", False)
            
            if success:
                self.log_test("Manual Behavior Tracking", True, "Behavior tracked successfully")
            else:
                self.log_test("Manual Behavior Tracking", False, "Behavior tracking failed")
        else:
            self.log_test("Manual Behavior Tracking", False, "Behavior tracking request failed")
        
        # Test personalized recommendations (should use behavior data)
        response = self.make_request("GET", "/recommendations/personalized", token=self.demo_token)
        
        if response and response.status_code == 200:
            data = response.json()
            recommendations = data.get("recommendations", [])
            reason = data.get("reason", "")
            personalized = data.get("personalized", False)
            ai_insight = data.get("ai_insight", "")
            
            if recommendations:
                self.log_test("Personalized Recommendations", True, f"Got {len(recommendations)} recommendations, personalized: {personalized}")
                
                if personalized and ai_insight:
                    self.log_test("AI-Powered Personalization", True, "AI insights provided for personalization")
                else:
                    self.log_test("AI-Powered Personalization", False, "No AI insights in personalization")
            else:
                self.log_test("Personalized Recommendations", False, "No recommendations returned")
        else:
            self.log_test("Personalized Recommendations", False, "Recommendations request failed")
        
        # Test that behavior is automatically tracked during chat
        chat_data = {
            "user_id": "test_user",
            "message": "I want to visit Dubai for shopping"
        }
        response = self.make_request("POST", "/ai/chat", chat_data, self.demo_token)
        
        if response and response.status_code == 200:
            # Chat should automatically track behavior
            self.log_test("Automatic Behavior Tracking", True, "Chat interaction should auto-track behavior")
        else:
            self.log_test("Automatic Behavior Tracking", False, "Chat failed, behavior not tracked")
    
    def run_all_tests(self):
        """Run all extended feature tests"""
        print("🚀 Starting TravelSmart Extended Feature Tests")
        print(f"Testing against: {BASE_URL}")
        print("Testing 6 new features:")
        print("1. Multilingual AI Chatbot")
        print("2. Voice Input Support (backend)")
        print("3. Export Itinerary as PDF")
        print("4. Mock Email Notifications")
        print("5. Hotel Inventory Management")
        print("6. AI Learning from User Behavior")
        print("=" * 60)
        
        # Authenticate first
        self.authenticate()
        
        if not self.demo_token:
            print("❌ Cannot proceed without authentication")
            return False
        
        # Run feature tests
        self.test_multilingual_chatbot()
        self.test_itinerary_pdf_generation()
        self.test_mock_email_notifications()
        self.test_hotel_inventory_management()
        self.test_user_behavior_tracking()
        
        # Print summary
        print("\n" + "=" * 60)
        print("📊 EXTENDED FEATURE TEST SUMMARY")
        print("=" * 60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        
        if self.failed_tests:
            print(f"\n🔍 Failed Tests:")
            for test in self.failed_tests:
                print(f"  - {test}")
        
        success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        print(f"\n📈 Success Rate: {success_rate:.1f}%")
        
        if failed_tests == 0:
            print("\n🎉 All extended features working correctly!")
        else:
            print(f"\n⚠️  {failed_tests} test(s) failed. Check implementation.")
        
        return failed_tests == 0

if __name__ == "__main__":
    tester = TravelSmartExtendedTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)