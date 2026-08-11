"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle, Loader2, XCircle } from "lucide-react";
import Link from "next/link";

function OAuthCallbackContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("Completing authorization…");

  useEffect(() => {
    const integrationId = searchParams?.get("state");
    const code = searchParams?.get("code");
    const error = searchParams?.get("error");

    if (error) {
      setStatus("error");
      setMessage(`Authorization denied: ${error}`);
      return;
    }

    if (!integrationId) {
      setStatus("error");
      setMessage("Missing integration identifier.");
      return;
    }

    // Exchange code via backend when OAuth token endpoint is wired.
    // For now, mark connected if a code was returned (dev placeholder).
    if (code) {
      fetch(`/api/integrations/${integrationId}/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: code }),
      })
        .then((r) => r.json())
        .then(() => {
          setStatus("success");
          setMessage(`${integrationId.replace(/_/g, " ")} connected successfully.`);
          setTimeout(() => router.push("/integrations"), 2000);
        })
        .catch(() => {
          setStatus("error");
          setMessage("Failed to complete authorization.");
        });
    } else {
      setStatus("error");
      setMessage("No authorization code received.");
    }
  }, [searchParams, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-synthai-background p-6">
      <div className="w-full max-w-md rounded-xl border border-synthai-border bg-synthai-surface p-8 text-center">
        {status === "loading" && <Loader2 className="mx-auto mb-4 h-10 w-10 animate-spin text-brand-400" />}
        {status === "success" && <CheckCircle className="mx-auto mb-4 h-10 w-10 text-emerald-400" />}
        {status === "error" && <XCircle className="mx-auto mb-4 h-10 w-10 text-red-400" />}
        <p className="text-text-primary">{message}</p>
        {status !== "loading" && (
          <Link
            href="/integrations"
            className="mt-6 inline-block text-sm font-medium text-brand-400 hover:text-brand-300"
          >
            Back to Plugins
          </Link>
        )}
      </div>
    </div>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-synthai-background">
          <Loader2 className="h-8 w-8 animate-spin text-brand-400" />
        </div>
      }
    >
      <OAuthCallbackContent />
    </Suspense>
  );
}
