"use client";

import { useState, useRef, useEffect } from "react";
import { LogOut, User } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export function NavUser() {
  const { user, loading, signOut, openAuthModal } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  if (loading) return null;

  if (!user) {
    return (
      <button
        onClick={openAuthModal}
        className="rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white/80"
      >
        Sign in
      </button>
    );
  }

  const email = user.email ?? "";
  const avatarUrl = user.user_metadata?.avatar_url as string | undefined;
  const initial = (email[0] ?? "?").toUpperCase();

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setMenuOpen(!menuOpen)}
        className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1.5 text-xs text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white/80"
      >
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt=""
            className="h-5 w-5 rounded-full"
          />
        ) : (
          <div className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-500/20 text-[10px] font-bold text-indigo-400">
            {initial}
          </div>
        )}
        <span className="max-w-[120px] truncate">{email}</span>
      </button>

      {menuOpen && (
        <div className="absolute right-0 top-full mt-1.5 w-44 rounded-lg border border-white/[0.08] bg-[#0c0c0e] py-1 shadow-xl">
          <button
            onClick={async () => {
              setMenuOpen(false);
              await signOut();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-xs text-white/50 transition-colors hover:bg-white/[0.04] hover:text-white/70"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
