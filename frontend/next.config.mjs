/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The API base is server-side only: the browser talks to this app's route
  // handlers, so no token or endpoint ever reaches client JavaScript.
  env: { API_BASE: process.env.API_BASE ?? "http://localhost:8000" },
};
export default nextConfig;
