"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";

export function NavLogo() {
  const router = useRouter();

  return (
    <div
      onClick={() => {
        router.push("/");
        router.refresh();
      }}
      className="flex cursor-pointer items-center gap-2 transition-opacity hover:opacity-80"
    >
      <Image src="/AA.png" alt="" width={32} height={32} className="h-8 w-8" priority />
      <span className="text-[15px] font-semibold tracking-tight text-white/90">
        AnimeAI
      </span>
    </div>
  );
}
