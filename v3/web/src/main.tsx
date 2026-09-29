import {StrictMode} from "react";
import {createRoot} from "react-dom/client";
import App from "./App";
import "./styles.css";
import {initializeAppearance} from "./lib/appearance";
import {createBrowserRouter, RouterProvider} from "react-router-dom";

initializeAppearance();
const router = createBrowserRouter([{path: "*", element: <App />}]);
createRoot(document.getElementById("root")!).render(<StrictMode><RouterProvider router={router} /></StrictMode>);
