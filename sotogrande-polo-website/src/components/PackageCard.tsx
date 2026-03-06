import Image from "next/image";
import Link from "next/link";
import type { Package } from "@/lib/data";

export default function PackageCard({ pkg }: { pkg: Package }) {
  return (
    <div className="group bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-lg transition-shadow border border-cream-dark">
      <div className="relative h-52 overflow-hidden">
        <Image
          src={pkg.heroImage}
          alt={`${pkg.name} in Sotogrande, Spain`}
          fill
          className="object-cover group-hover:scale-105 transition-transform duration-500"
          sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
        />
        <div className="absolute top-3 right-3 bg-navy/90 text-white text-xs font-semibold px-3 py-1 rounded-full">
          {pkg.duration}
        </div>
      </div>
      <div className="p-6">
        <h3 className="text-lg font-bold text-navy mb-1">{pkg.name}</h3>
        <p className="text-navy/60 text-sm mb-4 line-clamp-2">{pkg.tagline}</p>
        <div className="flex items-end justify-between">
          <div>
            <span className="text-2xl font-bold text-gold">{pkg.price}</span>
            <span className="text-navy/50 text-xs ml-1">{pkg.priceNote}</span>
          </div>
          <Link
            href={`/packages/${pkg.slug}`}
            className="inline-flex items-center gap-1 text-sm font-semibold text-navy hover:text-gold transition-colors"
          >
            View Details
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        </div>
      </div>
    </div>
  );
}
