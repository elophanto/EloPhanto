"use client";

import { useState } from "react";

export default function ContactForm() {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Placeholder — will integrate with backend/Supabase in next phase
    setSubmitted(true);
  }

  if (submitted) {
    return (
      <div className="bg-green/5 border border-green/20 rounded-xl p-8 text-center">
        <div className="w-12 h-12 bg-green/10 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg className="w-6 h-6 text-green" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h3 className="text-lg font-bold text-navy mb-2">Thank you!</h3>
        <p className="text-navy/70 text-sm">
          We&apos;ve received your inquiry and will get back to you within 24 hours. Check your email for confirmation.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div>
          <label htmlFor="name" className="block text-sm font-medium text-navy mb-1.5">
            Full Name *
          </label>
          <input
            type="text"
            id="name"
            name="name"
            required
            className="w-full px-4 py-2.5 border border-cream-dark rounded-lg text-sm text-navy bg-white focus:outline-none focus:ring-2 focus:ring-gold/40 focus:border-gold"
            placeholder="Your full name"
          />
        </div>
        <div>
          <label htmlFor="email" className="block text-sm font-medium text-navy mb-1.5">
            Email *
          </label>
          <input
            type="email"
            id="email"
            name="email"
            required
            className="w-full px-4 py-2.5 border border-cream-dark rounded-lg text-sm text-navy bg-white focus:outline-none focus:ring-2 focus:ring-gold/40 focus:border-gold"
            placeholder="you@example.com"
          />
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div>
          <label htmlFor="phone" className="block text-sm font-medium text-navy mb-1.5">
            Phone
          </label>
          <input
            type="tel"
            id="phone"
            name="phone"
            className="w-full px-4 py-2.5 border border-cream-dark rounded-lg text-sm text-navy bg-white focus:outline-none focus:ring-2 focus:ring-gold/40 focus:border-gold"
            placeholder="+34 XXX XXX XXX"
          />
        </div>
        <div>
          <label htmlFor="inquiry" className="block text-sm font-medium text-navy mb-1.5">
            Inquiry Type *
          </label>
          <select
            id="inquiry"
            name="inquiry"
            required
            className="w-full px-4 py-2.5 border border-cream-dark rounded-lg text-sm text-navy bg-white focus:outline-none focus:ring-2 focus:ring-gold/40 focus:border-gold"
          >
            <option value="">Select an option</option>
            <option value="discovery">Polo Discovery — €199</option>
            <option value="weekend">Weekend Package — €599</option>
            <option value="week">Week Immersion — €1,499</option>
            <option value="corporate">Corporate Event — €2,500</option>
            <option value="lessons">Private Lessons — €150/hr</option>
            <option value="general">General Inquiry</option>
          </select>
        </div>
      </div>
      <div>
        <label htmlFor="message" className="block text-sm font-medium text-navy mb-1.5">
          Message *
        </label>
        <textarea
          id="message"
          name="message"
          required
          rows={4}
          className="w-full px-4 py-2.5 border border-cream-dark rounded-lg text-sm text-navy bg-white focus:outline-none focus:ring-2 focus:ring-gold/40 focus:border-gold resize-y"
          placeholder="Tell us about your group size, preferred dates, and any questions..."
        />
      </div>
      <button
        type="submit"
        className="w-full sm:w-auto px-8 py-3 bg-gold hover:bg-gold-dark text-white font-semibold rounded-lg transition-colors text-sm"
      >
        Send Inquiry
      </button>
    </form>
  );
}
