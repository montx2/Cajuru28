"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { obterToken } from "@/lib/auth";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.replace(obterToken() ? "/dashboard" : "/login");
  }, [router]);

  return null;
}
