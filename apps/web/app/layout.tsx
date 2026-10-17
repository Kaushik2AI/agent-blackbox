import type { Metadata } from "next";
// Fonts are bundled (no request to Google), so the page looks the same offline, on a
// remote server and on a public deployment.
import "@fontsource-variable/instrument-sans/wdth.css";
import "@fontsource-variable/jetbrains-mono/index.css";
import "./globals.css";
import { Nav } from "@/components/nav";
import { REPO_URL, SHOWCASE } from "@/lib/showcase";

export const metadata: Metadata = {
  title: "FlightPath: the flight recorder for AI agents",
  description:
    "Watch an AI agent work step by step. When it fails, see the step that broke, why, and re-run it with one change.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        {SHOWCASE && (
          <p className="border-b border-line bg-well px-4 py-2 text-center text-[13.5px] leading-5 text-fg-2" data-testid="showcase-banner">
            Showcase: real recorded runs and pre-recorded fixes, no server. Live AI and your own re-runs work when you{" "}
            <a className="font-medium text-fg underline underline-offset-4" href={`${REPO_URL}#quickstart`}>run FlightPath yourself</a>.
          </p>
        )}
        <Nav />
        {children}
      </body>
    </html>
  );
}
