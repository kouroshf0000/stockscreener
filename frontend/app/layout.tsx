import "./globals.css";
import type { Metadata } from "next";
import { IBM_Plex_Sans, Newsreader } from "next/font/google";
import { AppSidebar } from "@/components/ui/dashboard-with-collapsible-sidebar";

const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  weight: ["400", "500", "600"],
});

const serif = Newsreader({
  subsets: ["latin"],
  variable: "--font-serif",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "AlphaArchitect Terminal",
  description: "Institutional-grade equity research, screening, and valuation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${sans.variable} ${serif.variable} font-[var(--font-sans)]`} suppressHydrationWarning>
        <AppSidebar>{children}</AppSidebar>
      </body>
    </html>
  );
}
