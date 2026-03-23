import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { PosthogProvider } from "./providers";
import { AuthProvider } from "@/lib/auth-context";
import { AuthModal } from "@/components/auth-modal";
import { NavUser } from "@/components/nav-user";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AnimeAI",
  description: "AI-powered anime recommendations based on narrative DNA",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <PosthogProvider>
          <AuthProvider>
            <AuthModal />
            <nav className="sticky top-0 z-50 border-b border-white/[0.06] bg-[#09090b]/80 backdrop-blur-xl">
              <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
                <Link
                  href="/"
                  className="text-[15px] font-semibold tracking-tight text-white/90 transition-colors hover:text-white"
                >
                  AnimeAI
                </Link>
                <div className="flex items-center gap-3">
                  <span className="rounded-full border border-indigo-500/20 bg-indigo-500/5 px-2.5 py-0.5 text-[11px] font-medium text-indigo-400/60">
                    beta
                  </span>
                  <NavUser />
                </div>
              </div>
            </nav>
            <main className="mx-auto max-w-5xl px-6">{children}</main>
          </AuthProvider>
        </PosthogProvider>
      </body>
    </html>
  );
}
