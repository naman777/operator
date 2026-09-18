import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Operator | Mission Control",
  description: "Evidence-backed opportunity intelligence",
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
