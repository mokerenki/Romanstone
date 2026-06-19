// src/pages/_app.tsx
import { AppProps } from 'next/app';
import { QueryClient, QueryClientProvider } from 'react-query';
import { useState } from 'react';

/**
 * The root component for the app. It provides a single
 * QueryClient instance to all pages that use react‑query.
 */
export default function MyApp({ Component, pageProps }: AppProps) {
  // Create the client once – useState keeps the same instance
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <Component {...pageProps} />
    </QueryClientProvider>
  );
}
