import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // When running frontend locally (npm run dev), connect to Docker backend
    // When running in Docker, use the service name
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    return [
      {
        // Proxy all /api/* calls to the FastAPI backend
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        // Proxy WebSocket connections to the FastAPI backend
        source: "/ws/:path*",
        destination: `${backendUrl}/ws/:path*`,
      },
    ];
  },
  // Empty turbopack config to silence the warning
  // Turbopack handles WebSocket support natively in Next.js 16
  turbopack: {},
};

export default nextConfig;
