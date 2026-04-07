"""
TravelSmart API Backend Tests
Tests for: Auth, Destinations, Bookings, Stripe Payments, Itineraries, Chatbot
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://smart-itinerary-44.preview.emergentagent.com').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@travelsmart.com"
ADMIN_PASSWORD = "Admin@123"


class TestHealthAndBasics:
    """Basic health and connectivity tests"""
    
    def test_api_destinations_accessible(self):
        """GET /api/destinations should return list of destinations"""
        response = requests.get(f"{BASE_URL}/api/destinations")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Verify destination structure
        dest = data[0]
        assert "id" in dest
        assert "name" in dest
        assert "price" in dest
        assert "city" in dest
        print(f"✓ Found {len(data)} destinations")


class TestAuthentication:
    """Authentication endpoint tests"""
    
    def test_login_success(self):
        """POST /api/auth/login with valid credentials should return token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["email"] == ADMIN_EMAIL
        assert len(data["token"]) > 0
        print(f"✓ Login successful for {ADMIN_EMAIL}")
    
    def test_login_invalid_credentials(self):
        """POST /api/auth/login with invalid credentials should return 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpass"
        })
        assert response.status_code == 401
        print("✓ Invalid credentials correctly rejected")
    
    def test_auth_me_with_token(self):
        """GET /api/auth/me with valid token should return user info"""
        # First login
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        token = login_response.json()["token"]
        
        # Then get user info
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == ADMIN_EMAIL
        print("✓ Auth me endpoint working")
    
    def test_auth_me_without_token(self):
        """GET /api/auth/me without token should return 403"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 403
        print("✓ Unauthenticated request correctly rejected")


class TestDestinations:
    """Destination endpoint tests"""
    
    def test_get_all_destinations(self):
        """GET /api/destinations should return list"""
        response = requests.get(f"{BASE_URL}/api/destinations")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        print(f"✓ Retrieved {len(data)} destinations")
    
    def test_get_single_destination(self):
        """GET /api/destinations/{id} should return destination details"""
        # First get list
        list_response = requests.get(f"{BASE_URL}/api/destinations")
        destinations = list_response.json()
        dest_id = destinations[0]["id"]
        
        # Get single destination
        response = requests.get(f"{BASE_URL}/api/destinations/{dest_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == dest_id
        assert "name" in data
        assert "price" in data
        print(f"✓ Retrieved destination: {data['name']}")
    
    def test_get_nonexistent_destination(self):
        """GET /api/destinations/{invalid_id} should return 404"""
        response = requests.get(f"{BASE_URL}/api/destinations/nonexistent-id-12345")
        assert response.status_code == 404
        print("✓ Nonexistent destination correctly returns 404")


class TestBookings:
    """Booking endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    @pytest.fixture
    def destination_id(self):
        """Get a valid destination ID"""
        response = requests.get(f"{BASE_URL}/api/destinations")
        destinations = response.json()
        return destinations[0]["id"]
    
    def test_create_booking_success(self, auth_token, destination_id):
        """POST /api/bookings/create should create a booking"""
        # Use future date
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        
        response = requests.post(
            f"{BASE_URL}/api/bookings/create",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "item_type": "hotel",
                "item_id": destination_id,
                "travelers": 1,
                "travel_date": future_date,
                "details": {"test": True}
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "booking" in data
        assert data["booking"]["item_id"] == destination_id
        assert data["booking"]["status"] == "Confirmed (Payment Pending)"
        print(f"✓ Booking created: {data['booking']['id'][:8]}")
        return data["booking"]["id"]
    
    def test_create_booking_without_auth(self, destination_id):
        """POST /api/bookings/create without auth should return 403"""
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        
        response = requests.post(
            f"{BASE_URL}/api/bookings/create",
            json={
                "item_type": "hotel",
                "item_id": destination_id,
                "travelers": 1,
                "travel_date": future_date,
                "details": {}
            }
        )
        assert response.status_code == 403
        print("✓ Unauthenticated booking correctly rejected")
    
    def test_get_my_bookings(self, auth_token):
        """GET /api/bookings/my should return user's bookings"""
        response = requests.get(
            f"{BASE_URL}/api/bookings/my",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "bookings" in data
        assert "count" in data
        print(f"✓ Retrieved {data['count']} bookings")


class TestStripePayments:
    """Stripe payment integration tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    @pytest.fixture
    def booking_id(self, auth_token):
        """Create a booking and return its ID"""
        # Get destination
        dest_response = requests.get(f"{BASE_URL}/api/destinations")
        dest_id = dest_response.json()[0]["id"]
        
        # Create booking
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        response = requests.post(
            f"{BASE_URL}/api/bookings/create",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "item_type": "hotel",
                "item_id": dest_id,
                "travelers": 1,
                "travel_date": future_date,
                "details": {"test_stripe": True}
            }
        )
        return response.json()["booking"]["id"]
    
    def test_create_stripe_checkout_session(self, auth_token, booking_id):
        """POST /api/payments/create-checkout should create Stripe checkout session"""
        response = requests.post(
            f"{BASE_URL}/api/payments/create-checkout",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "booking_id": booking_id,
                "origin_url": "https://smart-itinerary-44.preview.emergentagent.com"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "checkout_url" in data
        assert "session_id" in data
        # Verify checkout_url is a valid Stripe URL
        assert "stripe.com" in data["checkout_url"] or "checkout" in data["checkout_url"]
        print(f"✓ Stripe checkout session created: {data['session_id'][:20]}...")
        return data["session_id"]
    
    def test_create_checkout_without_auth(self):
        """POST /api/payments/create-checkout without auth should return 403"""
        response = requests.post(
            f"{BASE_URL}/api/payments/create-checkout",
            json={
                "booking_id": "fake-booking-id",
                "origin_url": "https://example.com"
            }
        )
        assert response.status_code == 403
        print("✓ Unauthenticated checkout correctly rejected")
    
    def test_create_checkout_invalid_booking(self, auth_token):
        """POST /api/payments/create-checkout with invalid booking should return 404"""
        response = requests.post(
            f"{BASE_URL}/api/payments/create-checkout",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "booking_id": "nonexistent-booking-id",
                "origin_url": "https://example.com"
            }
        )
        assert response.status_code == 404
        print("✓ Invalid booking correctly returns 404")
    
    def test_get_checkout_status(self, auth_token, booking_id):
        """GET /api/payments/checkout-status/{session_id} should return status"""
        # First create checkout session
        checkout_response = requests.post(
            f"{BASE_URL}/api/payments/create-checkout",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "booking_id": booking_id,
                "origin_url": "https://smart-itinerary-44.preview.emergentagent.com"
            }
        )
        session_id = checkout_response.json()["session_id"]
        
        # Get status
        response = requests.get(
            f"{BASE_URL}/api/payments/checkout-status/{session_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "status" in data or "payment_status" in data
        assert "booking_id" in data
        print(f"✓ Checkout status retrieved: {data.get('payment_status', data.get('status'))}")
    
    def test_get_checkout_status_invalid_session(self, auth_token):
        """GET /api/payments/checkout-status/{invalid_id} should return 404"""
        response = requests.get(
            f"{BASE_URL}/api/payments/checkout-status/invalid-session-id",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 404
        print("✓ Invalid session correctly returns 404")


class TestItineraries:
    """Itinerary endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    def test_list_itineraries(self, auth_token):
        """GET /api/itinerary/list should return user's itineraries"""
        response = requests.get(
            f"{BASE_URL}/api/itinerary/list",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "itineraries" in data
        assert "count" in data
        print(f"✓ Retrieved {data['count']} itineraries")
    
    def test_list_itineraries_without_auth(self):
        """GET /api/itinerary/list without auth should return 403"""
        response = requests.get(f"{BASE_URL}/api/itinerary/list")
        assert response.status_code == 403
        print("✓ Unauthenticated itinerary list correctly rejected")


class TestWeatherAndRisk:
    """Weather and travel risk endpoint tests"""
    
    def test_get_weather(self):
        """GET /api/weather/{city} should return weather data"""
        response = requests.get(f"{BASE_URL}/api/weather/Mumbai")
        assert response.status_code == 200
        data = response.json()
        assert "city" in data
        assert "temperature" in data
        assert "condition" in data
        print(f"✓ Weather for Mumbai: {data['temperature']}°C, {data['condition']}")
    
    def test_get_weather_warning(self):
        """GET /api/weather-warning/{destination} should return warning data"""
        response = requests.get(f"{BASE_URL}/api/weather-warning/Dubai")
        assert response.status_code == 200
        data = response.json()
        assert "destination" in data
        assert "risk_level" in data
        assert "message" in data
        print(f"✓ Weather warning for Dubai: {data['risk_level']}")
    
    def test_get_travel_risk_index(self):
        """GET /api/travel-risk/{destination} should return risk score"""
        response = requests.get(f"{BASE_URL}/api/travel-risk/Paris?budget=100000")
        assert response.status_code == 200
        data = response.json()
        assert "risk_score" in data
        assert "category" in data
        assert "recommendation" in data
        print(f"✓ Travel risk for Paris: {data['risk_score']}/100 ({data['category']})")


class TestChatbot:
    """AI Chatbot endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    def test_ai_chat(self, auth_token):
        """POST /api/ai/chat should return AI response"""
        response = requests.post(
            f"{BASE_URL}/api/ai/chat",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "user_id": "test",
                "message": "Hello, what destinations do you recommend?"
            },
            timeout=30  # AI responses can take time
        )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert len(data["response"]) > 0
        print(f"✓ AI chat response received ({len(data['response'])} chars)")
    
    def test_ai_chat_without_auth(self):
        """POST /api/ai/chat without auth should return 403"""
        response = requests.post(
            f"{BASE_URL}/api/ai/chat",
            json={
                "user_id": "test",
                "message": "Hello"
            }
        )
        assert response.status_code == 403
        print("✓ Unauthenticated chat correctly rejected")


class TestFlightSearch:
    """Flight search endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["token"]
    
    def test_search_flights(self, auth_token):
        """POST /api/flights/search should return flight results"""
        future_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        
        response = requests.post(
            f"{BASE_URL}/api/flights/search",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "source": "Mumbai",
                "destination": "Delhi",
                "date": future_date,
                "passengers": 1
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "flights" in data
        assert "count" in data
        assert "source" in data
        print(f"✓ Found {data['count']} flights (source: {data['source']})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
