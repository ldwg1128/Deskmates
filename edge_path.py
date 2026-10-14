"""A clockwise perimeter with smooth, inward corner jumps."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class EdgePose:
    x: float
    y: float
    angle: float
    corner: bool
    fraction: float
    segment: int


class EdgeRoute:
    def __init__(self, left, top, width, height, radius, inset=8):
        self.left, self.top = left + inset, top + inset
        self.right, self.bottom = left + width - inset, top + height - inset
        width = max(1.0, self.right - self.left)
        height = max(1.0, self.bottom - self.top)
        self.radius = max(0.5, min(radius, width / 2, height / 2))
        r = self.radius
        self.lengths = (max(0.0, width - 2*r), math.pi*r/2,
                        max(0.0, height - 2*r), math.pi*r/2) * 2
        self.starts = []
        total = 0.0
        for length in self.lengths:
            self.starts.append(total)
            total += length
        self.length = total

    def locate(self, distance, direction=1):
        distance %= self.length
        probe = (distance + direction * 1e-7) % self.length
        for segment, (start, length) in enumerate(zip(self.starts, self.lengths)):
            if length and start <= probe < start + length:
                local = distance - start
                if local < -length / 2:
                    local += self.length
                return segment, min(1.0, max(0.0, local / length))
        raise ValueError("Invalid perimeter geometry")

    def at(self, distance, direction=1):
        segment, fraction = self.locate(distance, direction)
        l, t, r, b, radius = self.left, self.top, self.right, self.bottom, self.radius
        if segment % 2 == 0:
            endpoints = (((l+radius, t), (r-radius, t)),
                         ((r, t+radius), (r, b-radius)),
                         ((r-radius, b), (l+radius, b)),
                         ((l, b-radius), (l, t+radius)))
            first, last = endpoints[segment // 2]
            x = first[0] + (last[0] - first[0]) * fraction
            y = first[1] + (last[1] - first[1]) * fraction
            angle = (segment * 45 + 180) % 360
        else:
            centers = ((r-radius, t+radius), (r-radius, b-radius),
                       (l+radius, b-radius), (l+radius, t+radius))
            cx, cy = centers[segment // 2]
            theta = -90 + (segment // 2) * 90 + fraction * 90
            radians = math.radians(theta)
            x, y = cx + radius * math.cos(radians), cy + radius * math.sin(radians)
            angle = (theta - 90) % 360
        return EdgePose(x, y, angle, bool(segment % 2), fraction, segment)

    def remaining(self, distance, direction=1):
        segment, fraction = self.locate(distance, direction)
        return self.lengths[segment] * (1 - fraction if direction > 0 else fraction)

    def project(self, x, y):
        """Find the closest perimeter position without moving between monitors."""
        best_distance, best_position = float("inf"), 0.0
        for segment, length in enumerate(self.lengths):
            if not length:
                continue
            first = self.at(self.starts[segment] + 1e-6)
            last = self.at(self.starts[segment] + length - 1e-6)
            if segment % 2 == 0:
                dx, dy = last.x - first.x, last.y - first.y
                fraction = ((x-first.x)*dx + (y-first.y)*dy) / max(1e-12, dx*dx+dy*dy)
            else:
                centers = ((self.right-self.radius, self.top+self.radius),
                           (self.right-self.radius, self.bottom-self.radius),
                           (self.left+self.radius, self.bottom-self.radius),
                           (self.left+self.radius, self.top+self.radius))
                cx, cy = centers[segment // 2]
                start_angle = -90 + (segment // 2)*90
                theta = math.degrees(math.atan2(y-cy, x-cx))
                # Choose the angle equivalent closest to this quarter-circle.
                theta = min((theta-360, theta, theta+360),
                            key=lambda a: abs(a - (start_angle+45)))
                fraction = (theta - start_angle) / 90
            fraction = min(1.0, max(0.0, fraction))
            position = self.starts[segment] + length * fraction
            pose = self.at(position)
            distance = (x-pose.x)**2 + (y-pose.y)**2
            if distance < best_distance:
                best_distance, best_position = distance, position
        return best_position % self.length
