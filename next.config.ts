import type { NextConfig } from "next";

// Local-dev-only: where `next dev` proxies /api/py, /docs, /openapi.json to
// (the standard `uvicorn` dev server address). Has no effect in production.
const devApiUrl = "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  rewrites: async () => {
    return [
      {
        source: "/api/py/:path*",
        destination:
          process.env.NODE_ENV === "development"
            ? `${devApiUrl}/api/py/:path*`
            : "/api/",
      },
      {
        source: "/docs",
        destination:
          process.env.NODE_ENV === "development"
            ? `${devApiUrl}/api/py/docs`
            : "/api/py/docs",
      },
      {
        source: "/openapi.json",
        destination:
          process.env.NODE_ENV === "development"
            ? `${devApiUrl}/api/py/openapi.json`
            : "/api/py/openapi.json",
      },
    ];
  },
};

export default nextConfig;
