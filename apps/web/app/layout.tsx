import type { Metadata } from "next";
// Fonts are bundled (no request to Google), so the page looks the same offline, on a
// remote server and on a public deployment.
import "@fontsource-variable/instrument-sans/wdth.css";
import "@fontsource-variable/jetbrains-mono/index.css";
import "./globals.css";
import { Nav } from "@/components/nav";

export const metadata: Metadata = {
  title: "FlightPath: the flight recorder for AI agents",
  description:
    "Watch an AI agent work step by step. When it fails, see the step that broke, why, and re-run it with one change.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <Nav />
        {children}
      </body>
    </html>
  );
}
