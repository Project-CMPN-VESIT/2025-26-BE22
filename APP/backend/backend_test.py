#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import time

class TravelSmartAPITester:
    def __init__(self, base_url="https://smart-itinerary-44.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name} - PASSED")
        else:
            print(f"❌ {name} - FAILED: {details}")
        
        self.test_results.append({
            "name": name,
            "success": success,
            "details": details
        })

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}" if not endpoint.startswith('http') else endpoint
        
        # Handle health endpoint specially (no /api prefix)
        if endpoint == "health":
            url = f"{self.base_url}/health"
        
        test_headers = {'Content-Type': 'application/json'}
        if self.token:
            test_headers['Authorization'] = f'Bearer {self.token}'
        if headers:
            test_headers.update(headers)

        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=test_headers, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=test_headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers, timeout=30)

            print(f"   Status: {response.status_code}")
            
            success = response.status_code == expected_status
            
            if success:
                self.log_test(name, True)
                try:
                    return True, response.json()
                except:
                    return True, response.text
            else:
                error_detail = f"Expected {expected_status}, got {response.status_code}"
                try:
                    error_detail += f" - {response.json()}"
                except:
                    error_detail += f" - {response.text[:200]}"
                self.log_test(name, False, error_detail)
                return False, {}

        except Exception as e:
            self.log_test(name, False, f"Request failed: {str(e)}")
            return False, {}

    def test_health_endpoint(self):
        """Test health endpoint"""
        success, response = self.run_test(
            "Health Check",
            "GET",
            "health",
            200
        )
        
        if success and isinstance(response, dict):
            if response.get('status') == 'healthy':
                print(f"   ✅ Health status: {response.get('status')}")
                return True
            else:
                self.log_test("Health Status Validation", False, f"Expected 'healthy', got '{response.get('status')}'")
                return False
        return success

    def test_login(self):
        """Test login with demo credentials"""
        success, response = self.run_test(
            "Demo User Login",
            "POST",
            "auth/login",
            200,
            data={"email": "demo@travelapp.com", "password": "demo123"}
        )
        
        if success and 'token' in response:
            self.token = response['token']
            self.user_id = response.get('user', {}).get('id')
            print(f"   ✅ Token obtained: {self.token[:20]}...")
            return True
        return False

    def test_budget_aware_itinerary(self):
        """Test budget-aware itinerary generation"""
        if not self.token:
            self.log_test("Budget Itinerary (No Auth)", False, "No authentication token")
            return False

        # Test 1: Valid budget
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        
        success, response = self.run_test(
            "Budget Itinerary - Valid Budget",
            "POST",
            "itinerary/generate",
            200,
            data={
                "destination": "Goa",
                "days": 5,
                "travel_date": future_date,
                "interests": "Beach",
                "budget": 15000
            }
        )
        
        if success:
            # Check for daily_cost_estimate in response
            budget_info = response.get('budget_info', {})
            if 'daily_cost_estimate' in budget_info:
                print(f"   ✅ Daily cost estimate: ₹{budget_info['daily_cost_estimate']}")
            else:
                self.log_test("Daily Cost Estimate Check", False, "daily_cost_estimate not found in response")

        # Test 2: Budget too low
        success_low, response_low = self.run_test(
            "Budget Itinerary - Low Budget",
            "POST",
            "itinerary/generate",
            400,
            data={
                "destination": "Goa",
                "days": 5,
                "travel_date": future_date,
                "interests": "Beach",
                "budget": 1500
            }
        )
        
        if success_low:
            error_detail = response_low.get('detail', '')
            if 'Budget too low' in error_detail:
                print(f"   ✅ Low budget error: {error_detail}")
            else:
                self.log_test("Low Budget Error Check", False, f"Expected 'Budget too low' error, got: {error_detail}")

        return success and success_low

    def test_weather_warning(self):
        """Test weather warning endpoint"""
        success, response = self.run_test(
            "Weather Warning",
            "GET",
            "weather-warning/Goa",
            200
        )
        
        if success:
            required_fields = ['destination', 'risk_level', 'message']
            missing_fields = [field for field in required_fields if field not in response]
            
            if not missing_fields:
                risk_level = response.get('risk_level')
                if risk_level in ['safe', 'moderate', 'high']:
                    print(f"   ✅ Risk level: {risk_level}")
                    print(f"   ✅ Message: {response.get('message', '')[:50]}...")
                else:
                    self.log_test("Risk Level Validation", False, f"Invalid risk level: {risk_level}")
                    return False
            else:
                self.log_test("Weather Warning Fields", False, f"Missing fields: {missing_fields}")
                return False
        
        return success

    def test_pre_booking_buffer(self):
        """Test pre-booking buffer validation"""
        if not self.token:
            self.log_test("Pre-booking Buffer (No Auth)", False, "No authentication token")
            return False

        # First, get a destination to book
        success, destinations = self.run_test(
            "Get Destinations for Booking",
            "GET",
            "destinations",
            200
        )
        
        if not success or not destinations:
            self.log_test("Pre-booking Buffer Setup", False, "Could not get destinations")
            return False

        # Find any destination (prefer tour for testing)
        test_dest = None
        for dest in destinations:
            if dest.get('type') == 'tour':
                test_dest = dest
                break
        
        if not test_dest and destinations:
            test_dest = destinations[0]  # Use any available destination
        
        if not test_dest:
            self.log_test("Pre-booking Buffer Setup", False, "No destinations found")
            return False

        # Test booking with today's date (should fail)
        today = datetime.now().strftime("%Y-%m-%d")
        
        success, response = self.run_test(
            "Pre-booking Buffer - Today's Date",
            "POST",
            "bookings/create",
            400,
            data={
                "item_type": test_dest.get('type', 'tour'),
                "item_id": test_dest['id'],
                "travelers": 1,
                "travel_date": today,
                "details": {}
            }
        )
        
        if success:
            error_detail = response.get('detail', '')
            if 'minimum pre-booking buffer policy' in error_detail:
                print(f"   ✅ Pre-booking buffer error: {error_detail}")
                return True
            else:
                self.log_test("Pre-booking Buffer Error Check", False, f"Expected buffer policy error, got: {error_detail}")
                return False
        
        return success

    def test_destinations_api(self):
        """Test destinations API"""
        success, response = self.run_test(
            "Get Destinations",
            "GET",
            "destinations",
            200
        )
        
        if success and isinstance(response, list):
            print(f"   ✅ Found {len(response)} destinations")
            
            # Check if destinations have required fields
            if response:
                dest = response[0]
                required_fields = ['id', 'name', 'type', 'price']
                missing_fields = [field for field in required_fields if field not in dest]
                
                if not missing_fields:
                    print(f"   ✅ Destination structure valid")
                else:
                    self.log_test("Destination Structure", False, f"Missing fields: {missing_fields}")
                    return False
        
        return success

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting TravelSmart API Tests")
        print("=" * 50)
        
        # Test 1: Health endpoint
        self.test_health_endpoint()
        
        # Test 2: Login
        login_success = self.test_login()
        
        # Test 3: Destinations
        self.test_destinations_api()
        
        # Test 4: Weather warning
        self.test_weather_warning()
        
        # Tests requiring authentication
        if login_success:
            # Test 5: Budget-aware itinerary
            self.test_budget_aware_itinerary()
            
            # Test 6: Pre-booking buffer
            self.test_pre_booking_buffer()
        else:
            print("\n⚠️  Skipping authenticated tests due to login failure")
        
        # Print summary
        print("\n" + "=" * 50)
        print("📊 TEST SUMMARY")
        print("=" * 50)
        print(f"Tests Run: {self.tests_run}")
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Tests Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        # Print failed tests
        failed_tests = [test for test in self.test_results if not test['success']]
        if failed_tests:
            print("\n❌ FAILED TESTS:")
            for test in failed_tests:
                print(f"   • {test['name']}: {test['details']}")
        
        return self.tests_passed == self.tests_run

def main():
    tester = TravelSmartAPITester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
