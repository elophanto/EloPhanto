"use client";

import Link from "next/link";
import { useState } from "react";

export default function Header() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-white/95 backdrop-blur-sm border-b border-cream-dark">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 lg:h-20">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2">
            <div className="w-8 h-8 lg:w-10 lg:h-10 rounded-full bg-navy flex items-center justify-center">
              <span className="text-white font-bold text-sm lg:text-base">SP</span>
            </div>
            <div className="leading-tight">
              <span className="block text-navy font-bold text-sm lg:text-base tracking-wide">
                Sotogrande Polo
              </span>
              <span className="block text-gold text-[10px] lg:text-xs tracking-widest uppercase">
                Tourism
              </span>
            </div>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden lg:flex items-center gap-8">
            <Link
              href="/packages"
              className="text-navy/70 hover:text-navy text-sm font-medium transition-colors"
            >
              Packages
            </Link>
            <Link
              href="/packages/discovery"
              className="text-navy/70 hover:text-navy text-sm font-medium transition-colors"
            >
              Discovery
            </Link>
            <Link
              href="/packages/weekend"
              className="text-navy/70 hover:text-navy text-sm font-medium transition-colors"
            >
              Weekend
            </Link>
            <Link
              href="/packages/week-immersion"
              className="text-navy/70 hover:text-navy text-sm font-medium transition-colors"
            >
              Week Immersion
            </Link>
            <Link
              href="/about"
              className="text-navy/70 hover:text-navy text-sm font-medium transition-colors"
            >
              About
            </Link>
            <Link
              href="/contact"
              className="text-navy/70 hover:text-navy text-sm font-medium transition-colors"
            >
              Contact
            </Link>
          </nav>

          {/* CTA button */}
          <Link
            href="/contact"
            className="hidden lg:inline-flex items-center px-5 py-2.5 bg-gold hover:bg-gold-dark text-white text-sm font-semibold rounded-md transition-colors"
          >
            Book Now
          </Link>

          {/* Mobile menu toggle */}
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="lg:hidden p-2 text-navy"
            aria-label="Toggle menu"
          >
            {mobileOpen ? (
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="lg:hidden bg-white border-t border-cream-dark">
          <nav className="flex flex-col px-4 py-4 gap-1">
            {[
              { href: "/packages", label: "All Packages" },
              { href: "/packages/discovery", label: "Polo Discovery — €199" },
              { href: "/packages/weekend", label: "Weekend Package — €599" },
              { href: "/packages/week-immersion", label: "Week Immersion — €1,499" },
              { href: "/packages/corporate", label: "Corporate Events — €2,500" },
              { href: "/packages/lessons", label: "Private Lessons — €150/hr" },
              { href: "/about", label: "About Us" },
              { href: "/contact", label: "Contact" },
            ].map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className="px-3 py-2.5 text-navy/80 hover:text-navy hover:bg-cream rounded-md text-sm font-medium transition-colors"
              >
                {link.label}
              </Link>
            ))}
            <Link
              href="/contact"
              onClick={() => setMobileOpen(false)}
              className="mt-2 px-3 py-2.5 bg-gold hover:bg-gold-dark text-white text-center rounded-md text-sm font-semibold transition-colors"
            >
              Book Your Experience
            </Link>
          </nav>
        </div>
      )}
    </header>
  );
}
