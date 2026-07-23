"use client";

import { useEffect, useState } from "react";
import Header from "@/components/Header";
import CryptoTicker from "@/components/CryptoTicker";
import TabBar from "@/components/TabBar";
// StatusBar is the bottom system strip - historical filename Sidebar.tsx.
import StatusBar from "@/components/Sidebar";
import TradingTab from "@/components/tabs/TradingTab";
import AlphaTab from "@/components/tabs/AlphaTab";
import HeatmapTab from "@/components/tabs/HeatmapTab";
import ResearchTab from "@/components/tabs/ResearchTab";
import OrderFlowTab from "@/components/tabs/OrderFlowTab";
import AlertsTab from "@/components/tabs/AlertsTab";
import SystemDocsTab from "@/components/tabs/SystemDocsTab";
import TradingJournalTab from "@/components/tabs/TradingJournalTab";
import RiskTab from "@/components/tabs/RiskTab";
import DocsOverlay from "@/components/DocsOverlay";

const API = "http://localhost:8001";

type TabId = "trading" | "alpha" | "heatmap" | "research" | "orderflow" | "alerts" | "docs" | "journal" | "risk";

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>("trading");
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [navCollapsed, setNavCollapsed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch(`${API}/api/health`);
        const data: Record<string, unknown> = await res.json();
        if (!cancelled) setHealth(data);
      } catch {
        if (!cancelled) setHealth(null);
      }
    };
    void check();
    const interval = setInterval(() => void check(), 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.altKey) return;
      const map: Record<string, TabId> = {
        "1": "trading",
        "2": "alpha",
        "3": "heatmap",
        "4": "research",
        "5": "orderflow",
        "6": "alerts",
        "7": "docs",
        "8": "risk",
        "9": "journal",
      };
      const tab = map[e.key];
      if (tab) {
        e.preventDefault();
        setActiveTab(tab);
      }
    };
    const docsHandler = (e: KeyboardEvent) => {
      if (e.key === "?" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const tag = (e.target as HTMLElement).tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        e.preventDefault();
        setActiveTab("docs");
      }
    };
    window.addEventListener("keydown", handler);
    window.addEventListener("keydown", docsHandler);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("keydown", docsHandler);
    };
  }, []);

  return (
    <div
      className="flex flex-col h-screen overflow-hidden"
      style={{ background: "var(--surface)" }}
    >
      <Header health={health} symbol={symbol} onSymbolChange={setSymbol} api={API} />
      <CryptoTicker api={API} onSelect={setSymbol} />

      <div className="flex flex-1 min-h-0">
        <TabBar
          active={activeTab}
          onChange={setActiveTab}
          collapsed={navCollapsed}
          onToggleCollapse={() => setNavCollapsed((v) => !v)}
        />

        <main
          className="flex-1 overflow-auto"
          style={{ background: "var(--surface)" }}
        >
          <div
            key={activeTab}
            className="animate-slide-in"
            style={{ padding: activeTab === "trading" ? 0 : activeTab === "docs" ? 0 : activeTab === "journal" ? 0 : 16, minHeight: "100%", height: "100%" }}
          >
            {activeTab === "trading" ? <TradingTab symbol={symbol} api={API} onSymbolChange={setSymbol} /> : null}
            {activeTab === "alpha" ? <AlphaTab symbol={symbol} api={API} /> : null}
            {activeTab === "heatmap" ? <HeatmapTab symbol={symbol} api={API} /> : null}
            {activeTab === "research" ? <ResearchTab symbol={symbol} api={API} /> : null}
            {activeTab === "orderflow" ? <OrderFlowTab symbol={symbol} api={API} /> : null}
            {activeTab === "alerts" ? <AlertsTab symbol={symbol} api={API} /> : null}
            {activeTab === "docs" ? <SystemDocsTab /> : null}
            {activeTab === "journal" ? <TradingJournalTab api={API} /> : null}
            {activeTab === "risk" ? <RiskTab symbol={symbol} api={API} /> : null}
          </div>
        </main>
      </div>

      <StatusBar api={API} symbol={symbol} health={health} />
      <DocsOverlay />
    </div>
  );
}