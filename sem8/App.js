import React, { useState, useEffect, createContext } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import axios from "axios";
import { Toaster } from "@/components/ui/sonner";
import Home from "@/pages/Home";
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
import Services from "@/pages/Services";
import Booking from "@/pages/Booking";
import Payment from "@/pages/Payment";
import PaymentSuccess from "@/pages/PaymentSuccess";
import Recommendations from "@/pages/Recommendations";
import PlanTrip from "@/pages/PlanTrip";
import MapView from "@/pages/MapView";
import Profile from "@/pages/Profile";
import AdminDashboard from "@/pages/AdminDashboard";
import ItineraryPage from "@/pages/ItineraryPage";
import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import "@/App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || window.location.origin;
export const API = `${BACKEND_URL}/api`;

// Auth Context
export const AuthContext = createContext(null);

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;
      fetchUser();
    } else {
      setLoading(false);
    }
  }, []);

  const fetchUser = async () => {
    try {
      const response = await axios.get(`${API}/auth/me`);
      setUser(response.data);
    } catch (error) {
      localStorage.removeItem("token");
      delete axios.defaults.headers.common["Authorization"];
    } finally {
      setLoading(false);
    }
  };

  const login = (token, userData) => {
    localStorage.setItem("token", token);
    axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;
    setUser(userData);
  };

  const logout = () => {
    localStorage.removeItem("token");
    delete axios.defaults.headers.common["Authorization"];
    setUser(null);
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-xl">Loading...</div>
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      <BrowserRouter>
        <div className="App min-h-screen flex flex-col">
          <Navbar />
          <main className="flex-grow">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/login" element={!user ? <Login /> : <Navigate to="/" />} />
              <Route path="/signup" element={!user ? <Signup /> : <Navigate to="/" />} />
              <Route path="/services" element={<Services />} />
              <Route path="/booking/:id" element={user ? <Booking /> : <Navigate to="/login" />} />
              <Route path="/payment" element={user ? <Payment /> : <Navigate to="/login" />} />
              <Route path="/payment/success" element={user ? <PaymentSuccess /> : <Navigate to="/login" />} />
              <Route path="/recommendations" element={user ? <Recommendations /> : <Navigate to="/login" />} />
              <Route path="/plan-trip" element={user ? <PlanTrip /> : <Navigate to="/login" />} />
              <Route path="/map" element={<MapView />} />
              <Route path="/profile" element={user ? <Profile /> : <Navigate to="/login" />} />
              <Route path="/admin" element={user ? <AdminDashboard /> : <Navigate to="/login" />} />
              <Route path="/itinerary" element={user ? <ItineraryPage /> : <Navigate to="/login" />} />
            </Routes>
          </main>
          <Footer />
          <Toaster />
        </div>
      </BrowserRouter>
    </AuthContext.Provider>
  );
}

export default App;
