import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

import { PoweredBy } from "@/components/PoweredBy";

// shadcn's theme block reads --font-sans / --font-mono; next/font defines them.
const sans = Geist({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Financial RAG",
  description: "Hybrid retrieval over financial filings with validated citations",
};

const NAV = [
  { href: "/corpus", label: "Corpus" },
  { href: "/eval", label: "Quality" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Dark is the only theme this app ships; there is no toggle to keep in sync.
    <html
      lang="en"
      className={`dark ${sans.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      {/*
        Browser extensions (ColorZilla's `cz-shortcut-listen`, Grammarly, and
        others) add attributes to <body> before React hydrates, which reads as
        a server/client mismatch. suppressHydrationWarning applies to this
        element's own attributes only - a genuine mismatch inside the tree is
        still reported.
      */}
      <body
        className="min-h-screen bg-background text-foreground"
        suppressHydrationWarning
      >
        <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="mx-auto flex h-14 max-w-6xl items-center gap-8 px-6">
            <Link href="/" className="flex items-center gap-2">
              <span className="grid size-6 place-items-center rounded-[6px] bg-primary text-[11px] font-bold text-primary-foreground">
                FR
              </span>
              <span className="text-sm font-semibold tracking-tight">Financial RAG</span>
            </Link>

            <nav className="flex items-center gap-1">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  {n.label}
                </Link>
              ))}
            </nav>

            <PoweredBy />
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-6 py-10">{children}</main>
      </body>
    </html>
  );
}
