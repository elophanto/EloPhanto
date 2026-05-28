import { useEffect } from "react";
import { Building2, ArrowLeft, ShieldCheck, Mic, Target, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDataStore } from "@/stores/data";
import { useConnectionStore } from "@/stores/connection";
import { Badge } from "@/components/ui/badge";
import { PaginationBar } from "@/components/ui/pagination";
import { usePagination } from "@/hooks/use-pagination";

const TRUST_COLOR: Record<string, string> = {
  learning: "text-amber-500",
  trial: "text-blue-500",
  operating: "text-emerald-500",
};

export function CompaniesPage() {
  const {
    companies,
    companiesLoading,
    fetchCompanies,
    companyDetail,
    companyDetailLoading,
    fetchCompanyDetail,
    clearCompanyDetail,
  } = useDataStore();
  const status = useConnectionStore((s) => s.status);
  const pag = usePagination(companies, 24);

  useEffect(() => {
    if (status === "connected") fetchCompanies();
  }, [status, fetchCompanies]);

  if (companyDetail || companyDetailLoading) {
    return (
      <CompanyDetailView
        loading={companyDetailLoading}
        onBack={clearCompanyDetail}
      />
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <h1 className="font-mono text-sm uppercase tracking-[0.15em]">Companies</h1>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          {companies.length} ABE{companies.length !== 1 ? "s" : ""} — autonomous business entities
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {companiesLoading && companies.length === 0 ? (
          <Empty text="Loading companies..." />
        ) : companies.length === 0 ? (
          <Empty text="No companies. Create one with `elophanto company create <slug>`." />
        ) : (
          <div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {pag.pageItems.map((c) => (
              <button
                key={c.slug}
                onClick={() => fetchCompanyDetail(c.slug)}
                className="flex flex-col gap-2 rounded-lg border border-border/50 p-4 text-left transition-colors hover:border-border hover:bg-foreground/[2%]"
              >
                <div className="flex items-center gap-2">
                  <Building2 className="size-3.5 text-muted-foreground" />
                  <span className="font-mono text-xs">{c.name}</span>
                  {c.active && (
                    <Badge variant="outline" className="ml-auto text-[8px]">
                      active
                    </Badge>
                  )}
                </div>
                <span className="font-mono text-[10px] text-muted-foreground/60">
                  {c.slug}
                </span>
                <div className="mt-1 flex flex-wrap gap-1.5 font-mono text-[9px] uppercase tracking-[0.08em]">
                  <span className={cn("flex items-center gap-1", TRUST_COLOR[c.trust])}>
                    <ShieldCheck className="size-2.5" /> {c.trust}
                  </span>
                  <span className="text-muted-foreground/70">
                    voice:{c.voice}
                  </span>
                  <span className="text-muted-foreground/70">
                    strat:{c.strategy}
                  </span>
                  {c.blockers > 0 && (
                    <span className="text-amber-500">{c.blockers} blockers</span>
                  )}
                </div>
                <div className="mt-1 flex items-center justify-between font-mono text-[10px]">
                  <span className="text-muted-foreground/60">net 7d</span>
                  <span className={c.net_7d < 0 ? "text-red-500" : "text-emerald-500"}>
                    {c.net_7d < 0 ? "-" : ""}${Math.abs(c.net_7d).toFixed(2)}
                  </span>
                </div>
              </button>
            ))}
            </div>
            <PaginationBar {...pag} noun="company" nounPlural="companies" />
          </div>
        )}
      </div>
    </div>
  );
}

function CompanyDetailView({
  loading,
  onBack,
}: {
  loading: boolean;
  onBack: () => void;
}) {
  const detail = useDataStore((s) => s.companyDetail);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-border/50 px-6 py-4">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Companies
        </button>
        {detail && (
          <span className="ml-2 font-mono text-sm">{detail.name ?? detail.slug}</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
        {loading || !detail ? (
          <Empty text="Loading company..." />
        ) : (
          <>
            {/* Ledger */}
            <Section title="Ledger" icon={Building2}>
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Revenue" value={`$${detail.ledger.revenue.toFixed(2)}`} good />
                <Stat label="Spend" value={`$${detail.ledger.spend.toFixed(2)}`} />
                <Stat label="Tokens" value={detail.ledger.tokens.toLocaleString()} />
              </div>
            </Section>

            {/* Product */}
            {detail.product ? (
              <Section title="Product" icon={FileText}>
                <pre className="overflow-x-auto rounded-md bg-foreground/[3%] p-3 font-mono text-[10px] leading-relaxed text-muted-foreground">
                  {JSON.stringify(detail.product, null, 2)}
                </pre>
              </Section>
            ) : null}

            {/* Voice */}
            <Section title="Voice Contract" icon={Mic}>
              {detail.voice ? (
                <div className="space-y-2 font-mono text-[11px]">
                  <KV k="persona" v={detail.voice.persona} />
                  <KV k="tone" v={detail.voice.tone.join(", ")} />
                  <KV k="length" v={detail.voice.length_target} />
                  {detail.voice.banned_phrases.length > 0 && (
                    <KV k="banned" v={detail.voice.banned_phrases.join(", ")} />
                  )}
                </div>
              ) : (
                <Muted text="No voice contract — agent must draft, not send." />
              )}
            </Section>

            {/* Strategy */}
            <Section title="Strategy" icon={Target}>
              {detail.strategy ? (
                <div className="space-y-2">
                  <p className="font-mono text-xs">{detail.strategy.name}</p>
                  {detail.strategy.tagline && (
                    <p className="font-mono text-[11px] text-muted-foreground italic">
                      {detail.strategy.tagline}
                    </p>
                  )}
                  {detail.strategy.overview && (
                    <p className="text-[11px] leading-relaxed text-muted-foreground">
                      {detail.strategy.overview}
                    </p>
                  )}
                  <p className="font-mono text-[10px] text-muted-foreground/60">
                    {detail.strategy.tactics} tactics
                  </p>
                </div>
              ) : (
                <Muted text="No active strategy." />
              )}
              {detail.blockers.filter((b) => !b.resolved).length > 0 && (
                <div className="mt-3 space-y-1.5">
                  <p className="font-mono text-[9px] uppercase tracking-[0.1em] text-amber-500">
                    Open blockers
                  </p>
                  {detail.blockers
                    .filter((b) => !b.resolved)
                    .map((b) => (
                      <div key={b.id} className="rounded border border-amber-500/20 px-2 py-1.5">
                        <span className="font-mono text-[9px] uppercase text-amber-500">
                          {b.type}
                        </span>
                        <p className="text-[11px] text-muted-foreground">{b.description}</p>
                        <span className="font-mono text-[9px] text-muted-foreground/50">
                          → {b.proposal}
                        </span>
                      </div>
                    ))}
                </div>
              )}
            </Section>

            {/* Drafts */}
            <Section title="Pending Drafts" icon={FileText}>
              {detail.drafts.length === 0 ? (
                <Muted text="No pending drafts." />
              ) : (
                <div className="space-y-2">
                  {detail.drafts.map((d) => (
                    <div key={`${d.kind}-${d.id}`} className="rounded border border-border/40 p-2.5">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="text-[8px]">
                          {d.kind}
                        </Badge>
                        <span className="font-mono text-[9px] text-muted-foreground/50">
                          {d.id}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground line-clamp-3">
                        {d.preview}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </Section>
          </>
        )}
      </div>
    </div>
  );
}

// ── shared bits ──

function Section({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: typeof Building2;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Icon className="size-3.5 text-muted-foreground" />
        <h2 className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-lg border border-border/40 p-3">
      <p className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/60">
        {label}
      </p>
      <p className={cn("mt-1 font-mono text-sm", good && "text-emerald-500")}>{value}</p>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-2">
      <span className="w-16 shrink-0 text-muted-foreground/60">{k}</span>
      <span className="text-foreground/90">{v}</span>
    </div>
  );
}

function Muted({ text }: { text: string }) {
  return <p className="font-mono text-[11px] text-muted-foreground/60">{text}</p>;
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-40 items-center justify-center">
      <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
        {text}
      </span>
    </div>
  );
}
