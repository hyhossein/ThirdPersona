// Combined-experience entry: the app mounts only when the landing hands over.
import React from "react";
import { createRoot } from "react-dom/client";
import ThirdPersona from "./thirdpersona_v9.jsx";

window.__mountTP = (rootEl) => {
  createRoot(rootEl).render(React.createElement(ThirdPersona));
};
