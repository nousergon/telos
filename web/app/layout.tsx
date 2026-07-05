import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Telos — year-round tax planning",
  description:
    "Deterministic personal tax projection — estimated full-year liability, safe-harbor installments, and investment gains from Metron.",
  icons: {
    icon: [{ url: "/dash/favicon.svg", type: "image/svg+xml" }],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="mx-auto max-w-7xl px-6">
          <header className="flex items-center justify-between border-b border-line py-5">
            <Link href="/" className="flex items-baseline gap-3">
              <span className="text-base font-semibold uppercase tracking-[0.22em]">Telos</span>
              <span className="hidden text-[11px] uppercase tracking-[0.18em] text-muted sm:inline">
                year-round tax planning
              </span>
            </Link>
            <Link
              href="https://portfolio.nousergon.ai"
              className="text-xs uppercase tracking-wide text-muted hover:text-ink"
            >
              Metron portfolio →
            </Link>
          </header>
          <main className="py-8">{children}</main>
          <footer className="border-t border-line py-6 text-xs leading-relaxed text-muted">
            <p>
              Deterministic projection from the telos engine. Investment gains sourced from Metron (read-only).
              Descriptive, not advice.
            </p>
          </footer>
        </div>
      </body>
    </html>
  );
}
