/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: __dirname,
  
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000';
    console.log(`[Next.js] Proxying API requests to: ${backendUrl}`);
    
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: '/ws/:path*',
        destination: `${backendUrl}/ws/:path*`,
      },
    ];
  },
  
  // WebSocket upgrade support for dev server proxy
  async headers() {
    return [
      {
        source: '/ws/:path*',
        headers: [
          { key: 'Connection', value: 'Upgrade' },
          { key: 'Upgrade', value: 'websocket' },
        ],
      },
    ];
  },
};

module.exports = nextConfig;