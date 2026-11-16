/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: false,
  poweredByHeader: false,
  // standalone нужен только для Docker-образа (frontend/Dockerfile задаёт BUILD_STANDALONE=1).
  // Netlify и Vercel собирают через свой адаптер — им standalone не нужен.
  ...(process.env.BUILD_STANDALONE === '1' ? { output: 'standalone' } : {}),
};
