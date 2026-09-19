import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Operator | Evidence-backed opportunity intelligence",
  description:
    "A durable AI workflow for cited job research, candidate evidence matching, reviewable application drafts, and human-approved actions.",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
