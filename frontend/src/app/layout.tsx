import type { Metadata } from "next";
import "./globals.css";
import { ClientProviders } from "@/components/ClientProviders";

export const metadata: Metadata = {
  title: "BookAI — AI-Powered Book Summarization & Q&A",
  description:
    "Upload PDF or DOCX books and get AI-generated summaries with intelligent question-answering powered by RAG. Cite sources, explore insights, and understand books faster.",
  keywords: ["book summary", "AI summarizer", "RAG", "question answering", "PDF analysis"],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <ClientProviders>{children}</ClientProviders>
      </body>
    </html>
  );
}
