import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { NavLogo } from "@/components/nav-logo";
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
  icons: {
    icon: "/AA.png",
    apple: "/AA.png",
  },
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
                <NavLogo />
                <div className="flex items-center gap-3">
                  <span className="rounded-full border border-indigo-500/20 bg-indigo-500/5 px-2.5 py-0.5 text-[11px] font-medium text-indigo-400/60">
                    beta
                  </span>
                  <NavUser />
                </div>
              </div>
            </nav>
            <main className="mx-auto max-w-5xl px-6">{children}</main>
            <footer className="mt-20 border-t border-white/4 py-6 text-center">
              <a
                href="https://animeai.canny.io/animeai-feedback"
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-white/20 transition-colors hover:text-white/40"
              >
                Give feedback
              </a>
            </footer>
          </AuthProvider>
        </PosthogProvider>
      </body>
    </html>
  );
}
