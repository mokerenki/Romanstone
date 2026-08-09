import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ 
  subsets: ["latin"],
  display: 'swap',
  variable: '--font-inter',
});

export const metadata: Metadata = {
  title: "synthAI - Autonomous Agent Platform",
  description: "Enterprise-grade autonomous agents for business workflows. Built for compliance, security, and scale.",
  keywords: "autonomous agents, AI, enterprise, workflow automation, multi-agent",
  authors: [{ name: "synthAI" }],
  openGraph: {
    title: "synthAI - Autonomous Agent Platform",
    description: "Enterprise-grade autonomous agents for business workflows.",
    url: "https://synthai.world",
    siteName: "synthAI",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
      },
    ],
    locale: "en_US",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "synthAI - Autonomous Agent Platform",
    description: "Enterprise-grade autonomous agents for business workflows.",
    images: ["/og-image.png"],
  },
  icons: {
    icon: "/favicon.ico",
    apple: "/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="bg-synthai-background text-synthai-text antialiased">
        {children}
      </body>
    </html>
  );
}