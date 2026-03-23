"use client";

import { useEffect } from "react";
import { Auth } from "@supabase/auth-ui-react";
import { ThemeSupa } from "@supabase/auth-ui-shared";
import { X } from "lucide-react";
import { getSupabase } from "@/lib/supabase";
import { useAuth } from "@/lib/auth-context";

export function AuthModal() {
  const { authModalOpen, closeAuthModal } = useAuth();

  // Close on Escape key
  useEffect(() => {
    if (!authModalOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeAuthModal();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [authModalOpen, closeAuthModal]);

  if (!authModalOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) closeAuthModal();
      }}
    >
      <div className="relative w-full max-w-sm rounded-xl border border-white/[0.08] bg-[#0c0c0e] p-6 shadow-2xl">
        {/* Close button */}
        <button
          onClick={closeAuthModal}
          className="absolute right-3 top-3 rounded-md p-1 text-white/30 transition-colors hover:bg-white/[0.06] hover:text-white/60"
        >
          <X className="h-4 w-4" />
        </button>

        <h2 className="mb-1 text-lg font-semibold text-white/90">
          Sign in to AnimeAI
        </h2>
        <p className="mb-5 text-sm text-white/40">
          Rate anime and get personalized recommendations.
        </p>

        <Auth
          supabaseClient={getSupabase()}
          appearance={{
            theme: ThemeSupa,
            variables: {
              default: {
                colors: {
                  brand: "#6366f1",
                  brandAccent: "#4f46e5",
                  inputBackground: "rgba(255,255,255,0.03)",
                  inputBorder: "rgba(255,255,255,0.08)",
                  inputText: "white",
                  inputPlaceholder: "rgba(255,255,255,0.25)",
                  inputLabelText: "rgba(255,255,255,0.5)",
                  anchorTextColor: "rgba(99,102,241,0.8)",
                  defaultButtonBackground: "rgba(255,255,255,0.04)",
                  defaultButtonBorder: "rgba(255,255,255,0.08)",
                  defaultButtonText: "rgba(255,255,255,0.7)",
                  defaultButtonBackgroundHover: "rgba(255,255,255,0.08)",
                },
                borderWidths: {
                  buttonBorderWidth: "1px",
                  inputBorderWidth: "1px",
                },
                radii: {
                  borderRadiusButton: "8px",
                  buttonBorderRadius: "8px",
                  inputBorderRadius: "8px",
                },
              },
            },
          }}
          providers={["google"]}
          redirectTo={typeof window !== "undefined" ? `${window.location.origin}/auth/callback` : undefined}
          view="sign_in"
        />
      </div>
    </div>
  );
}
