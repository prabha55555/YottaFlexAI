import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { FacilityProvider, ToastProvider } from "./components/hooks";
import "@xyflow/react/dist/style.css";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ToastProvider>
        <FacilityProvider>
          <App />
        </FacilityProvider>
      </ToastProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
