import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { packages } from "@/lib/data";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateStaticParams() {
  return packages.map((pkg) => ({ slug: pkg.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const pkg = packages.find((p) => p.slug === slug);
  if (!pkg) return {};
  return {
    title: pkg.seo.title,
    description: pkg.seo.description,
    keywords: pkg.seo.keywords,
    openGraph: {
      title: pkg.seo.title,
      description: pkg.seo.description,
      images: [{ url: pkg.heroImage, width: 1200, height: 630, alt: pkg.name }],
    },
    alternates: {
      canonical: `https://sotograndepolo.com/packages/${slug}`,
    },
  };
}

export default async function PackageDetailPage({ params }: Props) {
  const { slug } = await params;
  const pkg = packages.find((p) => p.slug === slug);
  if (!pkg) notFound();

  const otherPackages = packages.filter((p) => p.slug !== slug).slice(0, 3);

  return (
    <>
      {/* Hero */}
      <section className="relative h-[50vh] min-h-[400px] flex items-end">
        <Image
          src={pkg.heroImage}
          alt={`${pkg.name} in Sotogrande, Spain`}
          fill
          className="object-cover"
          priority
          sizes="100vw"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-navy/80 via-navy/30 to-transparent" />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-12 w-full">
          <Link
            href="/packages"
            className="inline-flex items-center gap-1 text-white/70 hover:text-white text-sm mb-4 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            All Packages
          </Link>
          <h1
            className="text-3xl sm:text-4xl lg:text-5xl font-bold text-white mb-2"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            {pkg.name}
          </h1>
          <p className="text-white/80 text-lg">{pkg.tagline}</p>
        </div>
      </section>

      {/* Price bar */}
      <section className="bg-white border-b border-cream-dark sticky top-16 lg:top-20 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-6 text-sm text-navy/60">
            <span className="flex items-center gap-1.5">
              <svg className="w-4 h-4 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {pkg.duration}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="text-2xl font-bold text-gold">{pkg.price}</span>
              <span className="text-navy/50 text-xs">{pkg.priceNote}</span>
            </span>
          </div>
          <Link
            href="/contact"
            className="px-6 py-2.5 bg-gold hover:bg-gold-dark text-white font-semibold rounded-lg transition-colors text-sm"
          >
            Book This Experience
          </Link>
        </div>
      </section>

      {/* Content */}
      <section className="py-16 lg:py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
            {/* Main content */}
            <div className="lg:col-span-2 space-y-12">
              {/* Description */}
              <div>
                <h2 className="text-xl font-bold text-navy mb-3">Overview</h2>
                <p className="text-navy/70 leading-relaxed">{pkg.description}</p>
              </div>

              {/* What's included */}
              <div>
                <h2 className="text-xl font-bold text-navy mb-4">What&apos;s Included</h2>
                <ul className="space-y-2.5">
                  {pkg.includes.map((item) => (
                    <li key={item} className="flex items-start gap-2.5 text-sm text-navy/70">
                      <svg className="w-5 h-5 text-green shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Itinerary */}
              {pkg.itinerary && (
                <div>
                  <h2 className="text-xl font-bold text-navy mb-4">Itinerary</h2>
                  <div className="space-y-4">
                    {pkg.itinerary.map((day) => (
                      <div
                        key={day.day}
                        className="border border-cream-dark rounded-lg p-5 bg-white"
                      >
                        <h3 className="font-semibold text-navy mb-1">{day.day}</h3>
                        <p className="text-navy/70 text-sm leading-relaxed">{day.details}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* What to expect */}
              <div>
                <h2 className="text-xl font-bold text-navy mb-4">What to Expect</h2>
                <ul className="space-y-2.5">
                  {pkg.whatToExpect.map((item) => (
                    <li key={item} className="flex items-start gap-2.5 text-sm text-navy/70">
                      <svg className="w-4 h-4 text-gold shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Requirements */}
              <div>
                <h2 className="text-xl font-bold text-navy mb-4">Requirements</h2>
                <ul className="space-y-2 text-sm text-navy/70">
                  {pkg.requirements.map((req) => (
                    <li key={req} className="flex items-start gap-2">
                      <span className="text-navy/30 mt-1">•</span>
                      {req}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {/* Sidebar */}
            <div className="space-y-6">
              {/* Booking CTA card */}
              <div className="bg-white border border-cream-dark rounded-xl p-6 sticky top-36">
                <h3 className="font-bold text-navy mb-1">{pkg.name}</h3>
                <div className="flex items-end gap-1 mb-4">
                  <span className="text-3xl font-bold text-gold">{pkg.price}</span>
                  <span className="text-navy/50 text-sm pb-1">{pkg.priceNote}</span>
                </div>
                <ul className="space-y-2 mb-6 text-sm text-navy/60">
                  <li className="flex items-center gap-2">
                    <svg className="w-4 h-4 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    {pkg.duration}
                  </li>
                  <li className="flex items-center gap-2">
                    <svg className="w-4 h-4 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    All equipment included
                  </li>
                  <li className="flex items-center gap-2">
                    <svg className="w-4 h-4 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    Photos included
                  </li>
                  <li className="flex items-center gap-2">
                    <svg className="w-4 h-4 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                    </svg>
                    Professional instructor
                  </li>
                </ul>
                <Link
                  href="/contact"
                  className="block w-full text-center px-6 py-3 bg-gold hover:bg-gold-dark text-white font-semibold rounded-lg transition-colors text-sm mb-3"
                >
                  Book Now
                </Link>
                <p className="text-xs text-navy/40 text-center">
                  Free cancellation with 48 hours notice
                </p>
              </div>

              {/* Testimonial */}
              <div className="bg-navy/5 border border-cream-dark rounded-xl p-6">
                <div className="flex gap-0.5 mb-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <svg key={i} className="w-4 h-4 text-gold" fill="currentColor" viewBox="0 0 20 20">
                      <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                    </svg>
                  ))}
                </div>
                <blockquote className="text-navy/80 text-sm italic leading-relaxed mb-3">
                  &ldquo;{pkg.testimonial.quote}&rdquo;
                </blockquote>
                <p className="text-navy font-semibold text-sm">{pkg.testimonial.author}</p>
                <p className="text-navy/50 text-xs">{pkg.testimonial.location}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Other Packages */}
      <section className="py-16 lg:py-20 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2
            className="text-2xl font-bold text-navy mb-8 text-center"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            You Might Also Like
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {otherPackages.map((p) => (
              <div
                key={p.slug}
                className="border border-cream-dark rounded-xl p-5 bg-cream/30 hover:bg-cream transition-colors"
              >
                <h3 className="font-bold text-navy mb-1">{p.name}</h3>
                <p className="text-navy/60 text-sm mb-3">{p.tagline}</p>
                <div className="flex items-center justify-between">
                  <span className="text-gold font-bold text-lg">{p.price}</span>
                  <Link
                    href={`/packages/${p.slug}`}
                    className="text-sm font-semibold text-navy hover:text-gold transition-colors"
                  >
                    View Details →
                  </Link>
                </div>
              </div>
            ))}
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
            Ready to Book Your {pkg.name}?
          </h2>
          <p className="text-white/70 mb-8">
            Secure your spot today. We&apos;ll confirm your booking within 24 hours.
          </p>
          <Link
            href="/contact"
            className="inline-flex items-center justify-center px-7 py-3.5 bg-gold hover:bg-gold-dark text-white font-semibold rounded-lg transition-colors text-sm"
          >
            Book Now — {pkg.price}
          </Link>
        </div>
      </section>
    </>
  );
}
