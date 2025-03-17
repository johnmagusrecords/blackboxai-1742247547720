int calculateAverage(int arr[], int size) {
    int sum = 0;
    for (int i = 0; i < size; i++) {  // Correct loop condition
        sum += arr[i];
    }
    return sum / size;
}
