import axios from "axios";

export const API_BASE = "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE,
});

export default api;
