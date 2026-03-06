import type { Metadata } from "next";
import Link from "next/link";
import PackageCard from "@/components/PackageCard";
import { packages } from "@/lib/data";

export const metadata: Metadata = {
  title: "Polo Packages & Experiences in Sotogrande",
  description:
    "Browse our polo holiday packages in Sotogrande, Spain. From €199 discovery sessions to €1,499 week immersions. Transparent pricing, all-inclusive experiences. Compare and book online.",
  keywords: [
    "polo vacation packages",
    "polo holidays spain",
    "polo lessons sotogrande",
    "horse riding holidays andalucia",
    "polo experience spain",
  ],
  alternates: {
    canonical: "https://sotograndepolo.com/packages",
  },
};

export default function PackagesPage() {
  return (
    <>
      {/* Hero */}
      <section className="bg-navy text-white py-20 lg:py-28">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
            Our Packages
          </p>
          <h1
            className="text-4xl sm:text-5xl font-bold mb-4"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            Polo Experiences for Every Level
          </h1>
          <p className="text-white/70 text-lg max-w-2xl mx-auto leading-relaxed">
            From a two-hour taster to a five-day immersion, we have the perfect
            package for you. Transparent pricing — no hidden fees, no surprises.
          </p>
        </div>
      </section>

      {/* Package Cards */}
      <section className="py-16 lg:py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {packages.map((pkg) => (
              <PackageCard key={pkg.slug} pkg={pkg} />
            ))}
          </div>
        </div>
      </section>

      {/* Comparison Table */}
      <section className="pb-16 lg:pb-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2
            className="text-2xl sm:text-3xl font-bold text-navy mb-8 text-center"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            Compare Packages
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left border border-cream-dark rounded-xl overflow-hidden">
              <thead>
                <tr className="bg-navy text-white">
                  <th className="px-4 py-3 font-semibold">Feature</th>
                  <th className="px-4 py-3 font-semibold text-center">Discovery</th>
                  <th className="px-4 py-3 font-semibold text-center">Weekend</th>
                  <th className="px-4 py-3 font-semibold text-center">Week</th>
                  <th className="px-4 py-3 font-semibold text-center">Corporate</th>
                  <th className="px-4 py-3 font-semibold text-center">Private</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-cream-dark">
                {[
                  {
                    feature: "Price",
                    values: ["€199", "€599", "€1,499", "€2,500", "€150/hr"],
                  },
                  {
                    feature: "Duration",
                    values: ["2 hours", "2 days", "5 days", "Half-day", "1 hour"],
                  },
                  {
                    feature: "Experience Needed",
                    values: ["None", "None", "None", "None", "Any level"],
                  },
                  {
                    feature: "Equipment Included",
                    values: ["check", "check", "check", "check", "check"],
                  },
                  {
                    feature: "Meals Included",
                    values: ["Champagne", "2 lunches", "B & L daily", "Lunch", "—"],
                  },
                  {
                    feature: "Photos/Video",
                    values: ["20 photos", "50 photos", "100+ & video", "50+ & video", "Optional"],
                  },
                  {
                    feature: "Accommodation",
                    values: ["—", "Add-on", "Included", "—", "—"],
                  },
                  {
                    feature: "Certificate",
                    values: ["—", "check", "check", "check", "—"],
                  },
                  {
                    feature: "Group Size",
                    values: ["4–6", "4–6", "4–8", "6–12", "1-on-1"],
                  },
                ].map((row) => (
                  <tr key={row.feature} className="hover:bg-cream/50">
                    <td className="px-4 py-3 font-medium text-navy">{row.feature}</td>
                    {row.values.map((val, i) => (
                      <td key={i} className="px-4 py-3 text-center text-navy/70">
                        {val === "check" ? (
                          <svg className="w-5 h-5 text-green mx-auto" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          val
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-16 lg:py-20 bg-navy text-white text-center">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2
            className="text-2xl sm:text-3xl font-bold mb-4"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            Not Sure Which Package is Right?
          </h2>
          <p className="text-white/70 mb-8">
            Get in touch and we&apos;ll help you choose the perfect experience for your
            group, schedule, and budget.
          </p>
          <Link
            href="/contact"
            className="inline-flex items-center justify-center px-7 py-3.5 bg-gold hover:bg-gold-dark text-white font-semibold rounded-lg transition-colors text-sm"
          >
            Contact Us
          </Link>
        </div>
      </section>
    </>
  );
}
