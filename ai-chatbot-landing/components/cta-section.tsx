import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function CTASection() {
  return (
    <section className="border-t border-border/50 bg-muted/30 py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-primary to-emerald-600 px-6 py-16 text-center text-white shadow-xl sm:px-12 sm:py-20">
          {/* Decorative elements */}
          <div className="pointer-events-none absolute inset-0">
            <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
            <div className="absolute -bottom-10 -left-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
          </div>

          <div className="relative">
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Ready to experience smarter conversations?
            </h2>
            <p className="mx-auto mt-4 max-w-lg text-base text-white/80 sm:text-lg">
              Join thousands who&apos;ve already made the switch. Start for free — no
              credit card required.
            </p>
            <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center sm:gap-4">
              <Button
                size="lg"
                className="gap-2 bg-white text-primary hover:bg-white/90 hover:shadow-lg hover:shadow-white/20"
              >
                Get started for free
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button
                size="lg"
                variant="outline"
                className="gap-2 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
              >
                Talk to sales
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
