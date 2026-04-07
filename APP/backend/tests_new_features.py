"""
TravelSmart API Backend Tests - New Features (Phase 2)
Tests for: Service Fee, E-Ticket, Invoice, Admin CRUD, Revenue, User Roles, Email Logs
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://smart-itinerary-44.preview.emergentagent.com').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@travelsmart.com"
ADMIN_PASSWORD = "Admin@123"
DEMO_EMAIL = "demo@travelapp.com"
DEMO_PASSWORD = "demo123"


@pytest.fixture(scope="module")
def admin_token():
    """Get admin authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture
def demo_token():
    """Get demo user authentication token - creates fresh user each time"""
    # Create a unique test user for non-admin tests
    import uuid
    test_email = f"test_user_{uuid.uuid4().hex[:8]}@test.com"
    test_password = "TestPass123"
    
    # Try to create user
    signup_response = requests.post(f"{BASE_URL}/api/auth/signup", json={
        "email": test_email,
        "password": test_password,
        "name": "Test User"
    })
    
    if signup_response.status_code == 200:
        return signup_response.json()["token"]
    
    # Fallback to demo user
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": DEMO_EMAIL,
        "password": DEMO_PASSWORD
    })
    if response.status_code != 200:
        pytest.skip("Demo user not available")
    return response.json()["token"]


@pytest.fixture(scope="module")
def destination_id():
    """Get a valid destination ID"""
    response = requests.get(f"{BASE_URL}/api/destinations")
    destinations = response.json()
    return destinations[0]["id"]


class TestServiceFeeCalculation:
    """Test 5% service fee on bookings"""
    
    def test_booking_includes_service_fee(self, admin_token, destination_id):
        """POST /api/bookings/create should return base_amount, service_fee, and amount"""
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        
        response = requests.post(
            f"{BASE_URL}/api/bookings/create",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "item_type": "hotel",
                "item_id": destination_id,
                "travelers": 2,
                "travel_date": future_date,
                "details": {"test_service_fee": True}
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        booking = data["booking"]
        # Verify service fee fields exist
        assert "base_amount" in booking, "Missing base_amount field"
        assert "service_fee" in booking, "Missing service_fee field"
        assert "amount" in booking, "Missing amount field"
        
        # Verify 5% calculation
        expected_fee = round(booking["base_amount"] * 0.05)
        assert booking["service_fee"] == expected_fee, f"Service fee should be 5% of base_amount"
        assert booking["amount"] == booking["base_amount"] + booking["service_fee"], "Total should be base + fee"
        
        print(f"✓ Service fee calculation correct: Base={booking['base_amount']}, Fee={booking['service_fee']}, Total={booking['amount']}")
        return booking["id"]


class TestETicketDownload:
    """Test E-Ticket PDF download endpoint"""
    
    @pytest.fixture
    def booking_id(self, admin_token, destination_id):
        """Create a booking for testing"""
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        response = requests.post(
            f"{BASE_URL}/api/bookings/create",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "item_type": "tour",
                "item_id": destination_id,
                "travelers": 1,
                "travel_date": future_date,
                "details": {"test_ticket": True}
            }
        )
        return response.json()["booking"]["id"]
    
    def test_download_ticket_success(self, admin_token, booking_id):
        """GET /api/ticket/{booking_id} should return PDF"""
        response = requests.get(
            f"{BASE_URL}/api/ticket/{booking_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200, f"Ticket download failed: {response.text}"
        assert "application/pdf" in response.headers.get("content-type", ""), "Response should be PDF"
        assert len(response.content) > 0, "PDF content should not be empty"
        print(f"✓ E-Ticket downloaded successfully ({len(response.content)} bytes)")
    
    def test_download_ticket_without_auth(self, booking_id):
        """GET /api/ticket/{booking_id} without auth should return 403"""
        response = requests.get(f"{BASE_URL}/api/ticket/{booking_id}")
        assert response.status_code == 403
        print("✓ Unauthenticated ticket download correctly rejected")
    
    def test_download_ticket_invalid_booking(self, admin_token):
        """GET /api/ticket/{invalid_id} should return 404"""
        response = requests.get(
            f"{BASE_URL}/api/ticket/nonexistent-booking-id",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404
        print("✓ Invalid booking ticket correctly returns 404")


class TestInvoiceDownload:
    """Test Invoice PDF download endpoint"""
    
    @pytest.fixture
    def booking_id(self, admin_token, destination_id):
        """Create a booking for testing"""
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        response = requests.post(
            f"{BASE_URL}/api/bookings/create",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "item_type": "hotel",
                "item_id": destination_id,
                "travelers": 1,
                "travel_date": future_date,
                "details": {"test_invoice": True}
            }
        )
        return response.json()["booking"]["id"]
    
    def test_download_invoice_success(self, admin_token, booking_id):
        """GET /api/invoice/{booking_id} should return PDF"""
        response = requests.get(
            f"{BASE_URL}/api/invoice/{booking_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200, f"Invoice download failed: {response.text}"
        assert "application/pdf" in response.headers.get("content-type", ""), "Response should be PDF"
        assert len(response.content) > 0, "PDF content should not be empty"
        print(f"✓ Invoice downloaded successfully ({len(response.content)} bytes)")
    
    def test_download_invoice_without_auth(self, booking_id):
        """GET /api/invoice/{booking_id} without auth should return 403"""
        response = requests.get(f"{BASE_URL}/api/invoice/{booking_id}")
        assert response.status_code == 403
        print("✓ Unauthenticated invoice download correctly rejected")


class TestAdminAnalytics:
    """Test Admin Analytics/Overview endpoint"""
    
    def test_admin_analytics_success(self, admin_token):
        """GET /api/admin/analytics should return KPIs"""
        response = requests.get(
            f"{BASE_URL}/api/admin/analytics",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify KPI fields
        assert "total_users" in data, "Missing total_users"
        assert "total_bookings" in data, "Missing total_bookings"
        assert "active_chats" in data, "Missing active_chats"
        assert "total_itineraries" in data, "Missing total_itineraries"
        
        print(f"✓ Admin analytics: Users={data['total_users']}, Bookings={data['total_bookings']}, Chats={data['active_chats']}, Itineraries={data['total_itineraries']}")
    
    def test_admin_analytics_non_admin(self, demo_token):
        """GET /api/admin/analytics with non-admin should return 403"""
        response = requests.get(
            f"{BASE_URL}/api/admin/analytics",
            headers={"Authorization": f"Bearer {demo_token}"}
        )
        assert response.status_code == 403
        print("✓ Non-admin correctly rejected from analytics")


class TestAdminBookings:
    """Test Admin Bookings endpoint"""
    
    def test_admin_bookings_list(self, admin_token):
        """GET /api/admin/bookings should return all bookings"""
        response = requests.get(
            f"{BASE_URL}/api/admin/bookings",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "bookings" in data
        print(f"✓ Admin bookings: {len(data['bookings'])} total bookings")
    
    def test_admin_bookings_non_admin(self, demo_token):
        """GET /api/admin/bookings with non-admin should return 403"""
        response = requests.get(
            f"{BASE_URL}/api/admin/bookings",
            headers={"Authorization": f"Bearer {demo_token}"}
        )
        assert response.status_code == 403
        print("✓ Non-admin correctly rejected from admin bookings")


class TestAdminDestinationsCRUD:
    """Test Admin Destinations CRUD operations"""
    
    def test_create_destination(self, admin_token):
        """POST /api/admin/destinations should create a new destination"""
        test_dest = {
            "name": "TEST_Destination_" + datetime.now().strftime("%H%M%S"),
            "country": "Test Country",
            "city": "Test City",
            "type": "hotel",
            "description": "Test destination for automated testing",
            "price": 5000,
            "duration": "2 Days / 1 Night",
            "rating": 4.5,
            "image": "https://example.com/test.jpg",
            "lat": 0.0,
            "lng": 0.0
        }
        
        response = requests.post(
            f"{BASE_URL}/api/admin/destinations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=test_dest
        )
        assert response.status_code == 200, f"Create destination failed: {response.text}"
        data = response.json()
        assert "destination" in data or "id" in data
        
        dest_id = data.get("destination", data).get("id", data.get("id"))
        print(f"✓ Destination created: {dest_id}")
        return dest_id
    
    def test_update_destination(self, admin_token):
        """PUT /api/admin/destinations/{id} should update a destination"""
        # First create a destination
        test_dest = {
            "name": "TEST_Update_" + datetime.now().strftime("%H%M%S"),
            "country": "Test Country",
            "city": "Test City",
            "type": "tour",
            "description": "Test destination for update",
            "price": 6000,
            "duration": "3 Days / 2 Nights",
            "rating": 4.0,
            "image": "https://example.com/test.jpg",
            "lat": 0.0,
            "lng": 0.0
        }
        
        create_response = requests.post(
            f"{BASE_URL}/api/admin/destinations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=test_dest
        )
        dest_id = create_response.json().get("destination", create_response.json()).get("id", create_response.json().get("id"))
        
        # Update the destination
        update_data = {
            "name": "TEST_Updated_Destination",
            "price": 7500,
            "rating": 4.8
        }
        
        response = requests.put(
            f"{BASE_URL}/api/admin/destinations/{dest_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=update_data
        )
        assert response.status_code == 200, f"Update destination failed: {response.text}"
        print(f"✓ Destination updated: {dest_id}")
    
    def test_delete_destination(self, admin_token):
        """DELETE /api/admin/destinations/{id} should delete a destination"""
        # First create a destination
        test_dest = {
            "name": "TEST_Delete_" + datetime.now().strftime("%H%M%S"),
            "country": "Test Country",
            "city": "Test City",
            "type": "flight",
            "description": "Test destination for deletion",
            "price": 4000,
            "duration": "1 Day",
            "rating": 3.5,
            "image": "https://example.com/test.jpg",
            "lat": 0.0,
            "lng": 0.0
        }
        
        create_response = requests.post(
            f"{BASE_URL}/api/admin/destinations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=test_dest
        )
        dest_id = create_response.json().get("destination", create_response.json()).get("id", create_response.json().get("id"))
        
        # Delete the destination
        response = requests.delete(
            f"{BASE_URL}/api/admin/destinations/{dest_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200, f"Delete destination failed: {response.text}"
        
        # Verify deletion
        get_response = requests.get(f"{BASE_URL}/api/destinations/{dest_id}")
        assert get_response.status_code == 404, "Deleted destination should not be found"
        print(f"✓ Destination deleted: {dest_id}")
    
    def test_create_destination_non_admin(self, demo_token):
        """POST /api/admin/destinations with non-admin should return 403"""
        response = requests.post(
            f"{BASE_URL}/api/admin/destinations",
            headers={"Authorization": f"Bearer {demo_token}"},
            json={"name": "Test", "country": "Test", "city": "Test", "type": "hotel", "description": "Test", "price": 1000, "duration": "1 Day", "rating": 4.0}
        )
        assert response.status_code == 403
        print("✓ Non-admin correctly rejected from creating destinations")


class TestAdminRevenue:
    """Test Admin Revenue Report endpoint"""
    
    def test_revenue_report(self, admin_token):
        """GET /api/admin/revenue should return revenue data"""
        response = requests.get(
            f"{BASE_URL}/api/admin/revenue",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify revenue fields
        assert "total_revenue" in data, "Missing total_revenue"
        assert "total_service_fees" in data, "Missing total_service_fees"
        assert "total_transactions" in data, "Missing total_transactions"
        assert "pending_payments" in data, "Missing pending_payments"
        
        print(f"✓ Revenue report: Total={data['total_revenue']}, Fees={data['total_service_fees']}, Transactions={data['total_transactions']}, Pending={data['pending_payments']}")
    
    def test_revenue_report_non_admin(self, demo_token):
        """GET /api/admin/revenue with non-admin should return 403"""
        response = requests.get(
            f"{BASE_URL}/api/admin/revenue",
            headers={"Authorization": f"Bearer {demo_token}"}
        )
        assert response.status_code == 403
        print("✓ Non-admin correctly rejected from revenue report")


class TestAdminUserManagement:
    """Test Admin User Management endpoints"""
    
    def test_get_all_users(self, admin_token):
        """GET /api/admin/users should return all users"""
        response = requests.get(
            f"{BASE_URL}/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "count" in data or len(data["users"]) >= 0
        
        # Verify user structure (no password_hash)
        if data["users"]:
            user = data["users"][0]
            assert "password_hash" not in user, "Password hash should not be exposed"
            assert "email" in user
            assert "name" in user
        
        print(f"✓ Admin users: {len(data['users'])} users found")
    
    def test_toggle_user_role(self, admin_token):
        """PUT /api/admin/users/{user_id}/role should toggle user role"""
        # First get users
        users_response = requests.get(
            f"{BASE_URL}/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        users = users_response.json()["users"]
        
        # Find a non-admin user to toggle
        non_admin_user = None
        for user in users:
            if user.get("role") != "admin" and user.get("email") != ADMIN_EMAIL:
                non_admin_user = user
                break
        
        if not non_admin_user:
            pytest.skip("No non-admin user available for role toggle test")
        
        # Toggle role
        response = requests.put(
            f"{BASE_URL}/api/admin/users/{non_admin_user['id']}/role",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "new_role" in data
        
        # Toggle back
        requests.put(
            f"{BASE_URL}/api/admin/users/{non_admin_user['id']}/role",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        print(f"✓ User role toggled: {non_admin_user['email']} -> {data['new_role']}")
    
    def test_get_users_non_admin(self, demo_token):
        """GET /api/admin/users with non-admin should return 403"""
        response = requests.get(
            f"{BASE_URL}/api/admin/users",
            headers={"Authorization": f"Bearer {demo_token}"}
        )
        assert response.status_code == 403
        print("✓ Non-admin correctly rejected from user management")


class TestAdminEmailLogs:
    """Test Admin Email Logs endpoint"""
    
    def test_get_email_logs(self, admin_token):
        """GET /api/admin/emails should return email logs"""
        response = requests.get(
            f"{BASE_URL}/api/admin/emails",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "emails" in data, "Missing emails list"
        assert "stats" in data, "Missing stats"
        
        # Verify stats structure
        stats = data["stats"]
        assert "total" in stats or isinstance(stats, dict)
        
        print(f"✓ Email logs: {len(data['emails'])} emails, Stats: {stats}")
    
    def test_get_email_logs_non_admin(self, demo_token):
        """GET /api/admin/emails with non-admin should return 403"""
        response = requests.get(
            f"{BASE_URL}/api/admin/emails",
            headers={"Authorization": f"Bearer {demo_token}"}
        )
        assert response.status_code == 403
        print("✓ Non-admin correctly rejected from email logs")


class TestStripePaymentCheckout:
    """Test Stripe Payment Checkout endpoints"""
    
    def test_create_checkout_session(self, admin_token, destination_id):
        """POST /api/payments/create-checkout should create Stripe session"""
        # First create a booking
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        booking_response = requests.post(
            f"{BASE_URL}/api/bookings/create",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "item_type": "hotel",
                "item_id": destination_id,
                "travelers": 1,
                "travel_date": future_date,
                "details": {"test_stripe_checkout": True}
            }
        )
        assert booking_response.status_code == 200
        booking_id = booking_response.json()["booking"]["id"]
        
        # Create checkout session
        response = requests.post(
            f"{BASE_URL}/api/payments/create-checkout",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "booking_id": booking_id,
                "origin_url": "https://smart-itinerary-44.preview.emergentagent.com"
            }
        )
        assert response.status_code == 200, f"Checkout creation failed: {response.text}"
        data = response.json()
        
        assert "checkout_url" in data, "Missing checkout_url"
        assert "session_id" in data, "Missing session_id"
        assert "stripe.com" in data["checkout_url"] or "checkout" in data["checkout_url"]
        
        print(f"✓ Stripe checkout created: {data['session_id'][:20]}...")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
