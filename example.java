public int sumEvenNumbers(int[] arr) {
    int sum = 0;
    for (int i = 0; i < arr.length; i++) {
        if (arr[i] % 2 == 0) {  // Correct condition
            sum += arr[i];
        }
    }
    return sum;
}
