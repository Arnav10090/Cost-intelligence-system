import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cost Intelligence — ET Gen AI Hackathon 2026",
  description:
    "Self-Healing Enterprise Cost Intelligence System. Monitors, detects, and autonomously fixes cost leakage across your enterprise.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark" style={{ colorScheme: "dark" }}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body style={{ background: "var(--bg-base)", color: "var(--text-primary)", minHeight: "100vh" }}>
        {children}
      </body>
    </html>
  );
}
