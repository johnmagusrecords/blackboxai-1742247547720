def calculate_average(numbers)
    return 0 if numbers.empty?
    sum = 0
    numbers.each { |number| sum += number }
    sum.to_f / numbers.count
end
