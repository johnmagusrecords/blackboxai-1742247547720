function sumNumbers(arr) {
    let sum = 0;
    for (let i = 0; i < arr.length; i++) {  // Correct condition
        sum += arr[i];
    }
    return sum;
}

// Test case
console.log(sumNumbers([1, 2, 3, 4]));  // Expected output: 10
