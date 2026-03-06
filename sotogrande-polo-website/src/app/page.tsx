import Image from "next/image";
import Link from "next/link";
import PackageCard from "@/components/PackageCard";
import TestimonialCard from "@/components/TestimonialCard";
import { packages, testimonials } from "@/lib/data";

export default function HomePage() {
  return (
    <>
      {/* Hero Section */}
      <section className="relative min-h-[85vh] flex items-center">
        <Image
          src="https://images.unsplash.com/photo-1565128939020-0f18a5c0960e?w=1920&q=80"
          alt="Polo players on the field in Sotogrande, Spain"
          fill
          className="object-cover"
          priority
        />
        <div className="absolute inset-0 bg-gradient-to-r from-navy/80 via-navy/50 to-transparent" />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20">
          <div className="max-w-2xl">
            <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-4">
              Sotogrande, Andalusia, Spain
            </p>
            <h1
              className="text-4xl sm:text-5xl lg:text-6xl font-bold text-white leading-tight mb-6"
              style={{ fontFamily: "var(--font-playfair), serif" }}
            >
              Experience Polo
              <br />
              in Sotogrande
            </h1>
            <p className="text-white/80 text-lg sm:text-xl leading-relaxed mb-8 max-w-lg">
              Premium polo experiences for complete beginners. No horse ownership,
              no experience needed — just unforgettable moments on the field.
            </p>
            <div className="flex flex-col sm:flex-row gap-4">
              <Link
                href="/packages/discovery"
                className="inline-flex items-center justify-center px-7 py-3.5 bg-gold hover:bg-gold-dark text-white font-semibold rounded-lg transition-colors text-sm"
              >
                Book Your First Experience — €199
              </Link>
              <Link
                href="/packages"
                className="inline-flex items-center justify-center px-7 py-3.5 bg-white/10 hover:bg-white/20 text-white font-semibold rounded-lg transition-colors text-sm border border-white/20"
              >
                View All Packages
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Trust bar */}
      <section className="bg-white border-b border-cream-dark">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-sm text-navy/50">
            <span className="flex items-center gap-2">
              <svg className="w-5 h-5 text-gold" fill="currentColor" viewBox="0 0 20 20">
                <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
              </svg>
              5-Star Rated Experiences
            </span>
            <span>In partnership with <strong className="text-navy">Polo Valley</strong></span>
            <span>In partnership with <strong className="text-navy">Santa Maria Polo Club</strong></span>
            <span>No Experience Required</span>
            <span>Transparent Pricing</span>
          </div>
        </div>
      </section>

      {/* Why Polo Section */}
      <section className="py-20 lg:py-28">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
              Why Choose Us
            </p>
            <h2
              className="text-3xl sm:text-4xl font-bold text-navy mb-4"
              style={{ fontFamily: "var(--font-playfair), serif" }}
            >
              The Sport of Kings, Made Accessible
            </h2>
            <p className="text-navy/60 text-base leading-relaxed">
              We partner with Sotogrande&apos;s finest polo clubs to offer complete
              tourism packages. You bring the curiosity — we provide everything else.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              {
                icon: (
                  <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                  </svg>
                ),
                title: "No Experience Needed",
                text: "Our programmes start from absolute zero. You don't need to know a horse from a mallet — our instructors will guide you every step of the way.",
              },
              {
                icon: (
                  <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                ),
                title: "Transparent Pricing",
                text: "Every price is on our website. No 'contact for a quote', no hidden fees, no surprises. What you see is what you pay.",
              },
              {
                icon: (
                  <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                  </svg>
                ),
                title: "Complete Experience",
                text: "We don't just offer lessons — we deliver memories. Equipment, lunch, photos, champagne, accommodation — everything is taken care of.",
              },
            ].map((item) => (
              <div
                key={item.title}
                className="text-center px-6 py-8 rounded-xl bg-white border border-cream-dark"
              >
                <div className="w-14 h-14 bg-gold/10 rounded-full flex items-center justify-center mx-auto mb-5 text-gold">
                  {item.icon}
                </div>
                <h3 className="text-lg font-bold text-navy mb-2">{item.title}</h3>
                <p className="text-navy/60 text-sm leading-relaxed">{item.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Packages Section */}
      <section className="py-20 lg:py-28 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
              Our Packages
            </p>
            <h2
              className="text-3xl sm:text-4xl font-bold text-navy mb-4"
              style={{ fontFamily: "var(--font-playfair), serif" }}
            >
              Choose Your Polo Experience
            </h2>
            <p className="text-navy/60 text-base leading-relaxed">
              From a two-hour discovery session to a five-day immersion — we have
              the perfect package for every level and occasion.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {packages.map((pkg) => (
              <PackageCard key={pkg.slug} pkg={pkg} />
            ))}
          </div>
          <div className="text-center mt-10">
            <Link
              href="/packages"
              className="inline-flex items-center gap-2 text-navy hover:text-gold font-semibold text-sm transition-colors"
            >
              View all packages &amp; compare
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
              </svg>
            </Link>
          </div>
        </div>
      </section>

      {/* Testimonials */}
      <section className="py-20 lg:py-28">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
              Guest Reviews
            </p>
            <h2
              className="text-3xl sm:text-4xl font-bold text-navy mb-4"
              style={{ fontFamily: "var(--font-playfair), serif" }}
            >
              What Our Guests Say
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {testimonials.slice(0, 6).map((t, i) => (
              <TestimonialCard key={i} {...t} />
            ))}
          </div>
        </div>
      </section>

      {/* Location Section */}
      <section className="py-20 lg:py-28 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            <div>
              <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
                Our Location
              </p>
              <h2
                className="text-3xl sm:text-4xl font-bold text-navy mb-4"
                style={{ fontFamily: "var(--font-playfair), serif" }}
              >
                Sotogrande, Andalusia
              </h2>
              <p className="text-navy/60 text-base leading-relaxed mb-6">
                Nestled on Spain&apos;s southern coast, Sotogrande is one of Europe&apos;s
                premier polo destinations. Year-round sunshine, world-class
                facilities, and the legendary hospitality of Andalusia.
              </p>
              <ul className="space-y-3 text-sm text-navy/70">
                {[
                  "20 minutes from Gibraltar Airport",
                  "90 minutes from Málaga Airport",
                  "300+ days of sunshine per year",
                  "Home to Santa Maria Polo Club & Polo Valley",
                  "Close to Marbella, Tarifa & the Costa del Sol",
                ].map((item) => (
                  <li key={item} className="flex items-center gap-2">
                    <svg className="w-4 h-4 text-gold shrink-0" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                    {item}
                  </li>
                ))}
              </ul>
              <Link
                href="/about"
                className="inline-flex items-center gap-2 mt-6 text-gold hover:text-gold-dark font-semibold text-sm transition-colors"
              >
                Learn more about us
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                </svg>
              </Link>
            </div>
            <div className="relative h-80 lg:h-[450px] rounded-xl overflow-hidden">
              <Image
                src="https://images.unsplash.com/photo-1509042239860-f550ce710b93?w=900&q=80"
                alt="Beautiful Sotogrande landscape in Andalusia, Spain"
                fill
                className="object-cover"
                sizes="(max-width: 1024px) 100vw, 50vw"
              />
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 lg:py-28 bg-navy text-white text-center">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2
            className="text-3xl sm:text-4xl font-bold mb-4"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            Ready to Experience Polo?
          </h2>
          <p className="text-white/70 text-lg mb-8 leading-relaxed">
            Join hundreds of guests who have discovered the thrill of polo in
            Sotogrande. Your adventure starts with a single booking.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link
              href="/packages/discovery"
              className="inline-flex items-center justify-center px-7 py-3.5 bg-gold hover:bg-gold-dark text-white font-semibold rounded-lg transition-colors text-sm"
            >
              Book Polo Discovery — €199
            </Link>
            <Link
              href="/contact"
              className="inline-flex items-center justify-center px-7 py-3.5 bg-white/10 hover:bg-white/20 text-white font-semibold rounded-lg transition-colors text-sm border border-white/20"
            >
              Contact Us
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
