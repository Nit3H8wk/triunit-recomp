#include "mk5_timing.hpp"
#include <iostream>
#include <stdexcept>

void need(bool value, const char* why) {
    if (!value) throw std::runtime_error(why);
}

int main() {
    try {
        need(mk5timing::ProducerDeadline(0, 100, 10, true) == 110, "first deadline");
        need(mk5timing::ProducerDeadline(110, 119, 10, true) == 120, "early producer retains cadence");
        need(mk5timing::ProducerDeadline(110, 999, 10, true) == 120, "late audio producer retains guest time");
        need(mk5timing::ProducerDeadline(110, 120, 10, false) == 120, "exact standalone boundary");
        need(mk5timing::ProducerDeadline(110, 121, 10, false) == 131, "late standalone rebase");
        mk5timing::Cadence cadence;
        cadence.interval = 10;
        cadence.presented(100);
        need(!cadence.due(109) && cadence.due(110), "exact presentation boundary");
        cadence.presented(105);
        need(cadence.next == 110, "early repaint keeps the next presentation deadline");
        cadence.presented(145);
        need(cadence.next == 150, "missed presentations coalesce without moving guest clock");
        mk5timing::Stats stats;
        need(stats.json().find("\"samples\":0") != std::string::npos, "empty stats are explicit");
        stats.observe(1000, 1000000);
        stats.observe(19279, 1000000);
        need(stats.n == 1 && std::abs(stats.sum - 18.279) < .0001, "tick frequency conversion");
        need(stats.percentile(.95) == 18.5, "histogram is an upper bound");
        stats.observe(19100, 1000000);
        need(stats.n == 1, "backward clock sample excluded");
        stats.observe(219100, 1000000);
        need(stats.n == 2 && stats.maximum == 200 && stats.bins.back() == 1,
             "overflow histogram retains true maximum");
        std::cout << "PASS producer/presentation boundaries, clock conversion, histogram overflow\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
