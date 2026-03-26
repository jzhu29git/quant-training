import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  typedRoutes: true,
  devIndicators: false,
  // This panel is often run through the local Docker override, which uses `next dev`.
  // Keep infrequently visited routes like `/overview` warm longer so guest logins do not
  // trigger the transient full-page build overlay after a short idle period.
  onDemandEntries: {
    maxInactiveAge: 1000 * 60 * 60 * 24,
    pagesBufferLength: 10
  }
};

export default nextConfig;
