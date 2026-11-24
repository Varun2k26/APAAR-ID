import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import { BRAND } from "./lib/brand";
import { AuthProvider, homeFor, useAuth } from "./lib/auth";
import Login from "./pages/public/Login";
import DigiLocker, { DigiLockerCallback } from "./pages/public/DigiLocker";
import Verify from "./pages/public/Verify";
import Overview from "./pages/aicte/Overview";
import Anomalies from "./pages/aicte/Anomalies";
import Conflicts from "./pages/shared/Conflicts";
import Institutions from "./pages/aicte/Institutions";
import InstitutionView from "./pages/aicte/InstitutionView";
import Audit from "./pages/aicte/Audit";
import SystemPage from "./pages/aicte/System";
import InstDashboard from "./pages/institution/Dashboard";
import Upload from "./pages/institution/Upload";
import AddStudent from "./pages/institution/AddStudent";
import Issues from "./pages/institution/Issues";
import Students from "./pages/institution/Students";
import Requests from "./pages/institution/Requests";
import Integration from "./pages/institution/Integration";
import StudentHome from "./pages/student/Home";
import Wallet from "./pages/student/Wallet";
import AccessLog from "./pages/student/AccessLog";
import Regulator from "./pages/regulator/Regulator";
import University from "./pages/university/University";

function Guard({ roles, children }: { roles: string[]; children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />;
  return <>{children}</>;
}

function Home() {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  return <Navigate to={user ? homeFor(user.role) : "/login"} replace />;
}

const INST = ["INSTITUTION_ADMIN", "DATA_OPERATOR"];
document.title = BRAND;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/mock-digilocker" element={<DigiLocker />} />
          <Route path="/auth/digilocker/callback" element={<DigiLockerCallback />} />
          <Route path="/verify" element={<Verify />} />
          <Route element={<Layout />}>
            <Route path="/aicte" element={<Guard roles={["AICTE_ADMIN"]}><Overview /></Guard>} />
            <Route path="/aicte/anomalies" element={<Guard roles={["AICTE_ADMIN"]}><Anomalies /></Guard>} />
            <Route path="/aicte/conflicts" element={<Guard roles={["AICTE_ADMIN"]}><Conflicts /></Guard>} />
            <Route path="/aicte/institutions" element={<Guard roles={["AICTE_ADMIN"]}><Institutions /></Guard>} />
            <Route path="/aicte/institutions/:id" element={<Guard roles={["AICTE_ADMIN"]}><InstitutionView /></Guard>} />
            <Route path="/aicte/audit" element={<Guard roles={["AICTE_ADMIN"]}><Audit /></Guard>} />
            <Route path="/aicte/system" element={<Guard roles={["AICTE_ADMIN"]}><SystemPage /></Guard>} />
            <Route path="/institution" element={<Guard roles={INST}><InstDashboard /></Guard>} />
            <Route path="/institution/upload" element={<Guard roles={INST}><Upload /></Guard>} />
            <Route path="/institution/add" element={<Guard roles={INST}><AddStudent /></Guard>} />
            <Route path="/institution/issues" element={<Guard roles={INST}><Issues /></Guard>} />
            <Route path="/institution/students" element={<Guard roles={INST}><Students /></Guard>} />
            <Route path="/institution/conflicts" element={<Guard roles={INST}><Conflicts /></Guard>} />
            <Route path="/institution/requests" element={<Guard roles={["INSTITUTION_ADMIN"]}><Requests /></Guard>} />
            <Route path="/institution/integration" element={<Guard roles={["INSTITUTION_ADMIN"]}><Integration /></Guard>} />
            <Route path="/student" element={<Guard roles={["STUDENT"]}><StudentHome /></Guard>} />
            <Route path="/student/wallet" element={<Guard roles={["STUDENT"]}><Wallet /></Guard>} />
            <Route path="/student/access" element={<Guard roles={["STUDENT"]}><AccessLog /></Guard>} />
            <Route path="/regulator" element={<Guard roles={["REGULATOR"]}><Regulator /></Guard>} />
            <Route path="/regulator/chain" element={<Guard roles={["REGULATOR"]}><Audit /></Guard>} />
            <Route path="/university" element={<Guard roles={["UNIVERSITY_REGISTRAR"]}><University /></Guard>} />
          </Route>
          <Route path="*" element={<Home />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
