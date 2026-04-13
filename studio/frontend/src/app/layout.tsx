import type { Metadata } from "next";
import "./globals.css";
import Navbar from "@/components/Navbar";

export const metadata: Metadata = {
  title: "Mark II Studio — Build. Break. Heal.",
  description: "Team-facing AI build platform. Submit a prompt or code, watch AI models build in parallel, then harden for production.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark h-full">
      <body className="h-full flex flex-col overflow-x-hidden grid-bg">
        <Navbar />
        <main className="flex-1 min-h-0 relative flex flex-col">
          {children}
        </main>
      </body>
    </html>
  );
}
